/*
 * Kindled Iron in-page renderer.
 *
 * Reads window.KI_DATA (written by render.py: scene with every event already
 * resolved to an absolute time and world coordinates), builds an SVG board,
 * stickman rigs and drawable objects, and one paused GSAP timeline.
 * render.py then calls window.kiSeek(t) for every frame and screenshots it.
 *
 * Ideas adapted from chrisaswain/stickman-animation-agent (MIT; see
 * kindled_iron/vendor/stickman-animation-agent/LICENSE): SVG stickmen with the
 * vendored head + expression components, stroke-dashoffset draw-in reveals,
 * a camera wrapper, expression swaps, point / wave / celebrate / head-shake
 * gestures. Rewritten here: an articulated rig (thigh/shin/upper arm/forearm)
 * with a procedural walk cycle, gestures aimed at real targets, and a
 * time-pure render(t) so every frame is deterministic.
 */
(function () {
  'use strict';
  var D = window.KI_DATA;
  var W = D.width, H = D.height;
  var C = D.palette;           // { board, ink, inkSoft, accent }
  var SVGNS = 'http://www.w3.org/2000/svg';
  var GROUND = D.ground;       // world y of the feet

  // ---------------------------------------------------------------- helpers
  function rng(seed) {         // deterministic PRNG (mulberry32)
    var a = seed >>> 0;
    return function () {
      a |= 0; a = a + 0x6D2B79F5 | 0;
      var t = Math.imul(a ^ a >>> 15, 1 | a);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }
  function hash(s) { var h = 2166136261; for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }
  function col(name) { return C[name] || name || C.ink; }
  function f(d, fill, fo, offset) {   // flat colour, fades in after the ink; offset = hand-coloured misregister
    return '<path d="' + d + '" stroke="none" fill="' + col(fill) + '" data-fill="' + (fo || 1) + '" fill-opacity="0"' +
      (offset === false ? '' : ' transform="translate(4,3)"') + '/>';
  }
  function p(d, o) {
    o = o || {};
    return (o.fill ? f(d, o.fill, o.fo, o.fill === 'board' ? false : true) : '') +
      '<path d="' + d + '" stroke="' + col(o.c) + '" stroke-width="' + (o.w || 7) + '" fill="none"' +
      ' stroke-linecap="round" stroke-linejoin="round"' + (o.op ? ' opacity="' + o.op + '"' : '') + '/>';
  }
  function circlePath(cx, cy, r) {
    return 'M' + (cx - r) + ',' + cy + ' a' + r + ',' + r + ' 0 1,0 ' + (2 * r) + ',0 a' + r + ',' + r + ' 0 1,0 ' + (-2 * r) + ',0';
  }
  function wobbleCircle(cx, cy, r, seed, amt) {   // slightly uneven hand-drawn circle
    var R = rng(seed), d = '', n = 14;
    for (var i = 0; i <= n; i++) {
      var a = i / n * Math.PI * 2 + 0.3, rr = r * (1 + (i === n ? 0 : (R() - 0.5) * (amt || 0.06)));
      var x = cx + Math.cos(a) * rr, y = cy + Math.sin(a) * rr;
      d += (i ? ' L' : 'M') + x.toFixed(1) + ',' + y.toFixed(1);
    }
    return d;
  }
  function smooth(pts) {        // Catmull-Rom -> cubic bezier path through points
    var d = 'M' + pts[0][0] + ',' + pts[0][1];
    for (var i = 0; i < pts.length - 1; i++) {
      var p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
      d += ' C' + (p1[0] + (p2[0] - p0[0]) / 6).toFixed(1) + ',' + (p1[1] + (p2[1] - p0[1]) / 6).toFixed(1) + ' ' +
        (p2[0] - (p3[0] - p1[0]) / 6).toFixed(1) + ',' + (p2[1] - (p3[1] - p1[1]) / 6).toFixed(1) + ' ' + p2[0].toFixed(1) + ',' + p2[1].toFixed(1);
    }
    return d;
  }

  // ---------------------------------------------------------------- objects
  // Each returns SVG markup centred on (0,0). Stroked paths draw themselves;
  // [data-fill] shapes fade their fill in after the stroke.
  var OBJ = {
    word: function (o) {
      var size = o.size || 120;
      return '<text class="ki-text" x="0" y="0" text-anchor="middle" dominant-baseline="central" ' +
        'font-family="Caveat" font-weight="700" font-size="' + size + '" fill="' + col(o.color) + '"' +
        (o.letterSpacing ? ' letter-spacing="' + o.letterSpacing + '"' : '') + '>' + esc(o.text || '') + '</text>' +
        (o.underline ? '<path class="ki-underline" d="" stroke="' + col(o.underline === true ? 'accent' : o.underline) +
          '" stroke-width="' + Math.max(6, size * 0.07) + '" fill="none" stroke-linecap="round"/>' : '');
    },
    strike: function () { return '<path class="ki-strike" d="" stroke="' + C.accent + '" stroke-width="16" fill="none" stroke-linecap="round"/>'; },
    circle: function () { return '<path class="ki-ring" d="" stroke="' + C.accent + '" stroke-width="9" fill="none" stroke-linecap="round"/>'; },
    rays: function (o) {
      var n = o.n || 12, r1 = o.r1 || 150, r2 = o.r2 || 210, s = '';
      var rx = o.rx || 1;  // horizontal stretch for wide words
      for (var i = 0; i < n; i++) {
        var a = i / n * Math.PI * 2 - Math.PI / 2;
        s += p('M' + (Math.cos(a) * r1 * rx).toFixed(1) + ',' + (Math.sin(a) * r1).toFixed(1) + ' L' + (Math.cos(a) * r2 * rx).toFixed(1) + ',' + (Math.sin(a) * r2).toFixed(1), { c: o.color || 'accent', w: 8 });
      }
      return s;
    },
    book: function (o) {
      var s = f('M-186,74 C-140,54 -60,54 0,76 C60,54 140,54 186,74 L186,84 C140,64 60,64 0,86 C-60,64 -140,64 -186,84 Z', 'shadow', 0.9, false) +
        p('M0,-60 C-60,-80 -140,-78 -190,-55 L-190,70 C-140,48 -60,48 0,70 Z', { fill: 'page', fo: 1 }) +
        p('M0,-60 C60,-80 140,-78 190,-55 L190,70 C140,48 60,48 0,70 Z', { fill: 'page', fo: 1 }) +
        p('M0,-60 L0,70', { w: 6 });
      for (var i = 0; i < 4; i++) {
        var y = -38 + i * 24;
        s += p('M-165,' + (y + 2) + ' C-120,' + (y - 8) + ' -60,' + (y - 8) + ' -25,' + (y + 4), { w: 4, c: 'inkSoft' });
        s += p('M25,' + (y + 4) + ' C60,' + (y - 8) + ' 120,' + (y - 8) + ' 165,' + (y + 2), { w: 4, c: 'inkSoft' });
      }
      if (o.ribbon !== false) s += p('M40,62 L40,120 L55,105 L70,120 L70,60', { c: 'accent', w: 6, fill: 'accent', fo: 0.9 });
      return s;
    },
    darkness: function (o) {     // dense charcoal hatching inside an ellipse
      var w = o.w || 700, h = o.h || 500, R = rng(hash(o.id)), s = '', rows = o.rows || 26;
      for (var i = 0; i < rows; i++) {
        var y = -h / 2 + (i + 0.5) * h / rows, half = w / 2 * Math.sqrt(Math.max(0, 1 - Math.pow(y / (h / 2), 2)));
        half *= 0.85 + R() * 0.25;
        var pts = [], x = -half, up = true;
        while (x < half) { pts.push([x, y + (up ? -h / rows * 1.4 : h / rows * 1.4) + (R() - 0.5) * 6]); x += 26 + R() * 14; up = !up; }
        if (pts.length > 1) s += '<path d="M' + pts.map(function (q) { return q[0].toFixed(0) + ',' + q[1].toFixed(0); }).join(' L') +
          '" stroke="' + C.ink + '" stroke-width="' + (5 + R() * 3).toFixed(1) + '" fill="none" stroke-linecap="round" stroke-linejoin="round" opacity="0.88"/>';
      }
      return s;
    },
    blob: function (o) {          // "formless": an unclosed wandering squiggle
      var R = rng(hash(o.id)), r = o.r || 160, pts = [];
      for (var i = 0; i < 22; i++) { var a = i * 0.62, rr = r * (0.45 + R() * 0.6); pts.push([Math.cos(a) * rr, Math.sin(a) * rr * 0.8]); }
      return f(wobbleCircle(0, 0, r * 0.75, 21, 0.4), 'shadow', 0.8) + p(smooth(pts), { w: 6 });
    },
    waves: function (o) {
      var w = o.w || 600, rows = o.rows || 3, s = '';
      var bottom = (rows - 1) * 42 + 34;
      s += f('M' + (-w / 2 - 10) + ',-6 C' + (-w / 6) + ',-20 ' + (w / 6) + ',8 ' + (w / 2 + 10) + ',-6 L' + (w / 2 + 6) + ',' + bottom +
        ' C' + (w / 6) + ',' + (bottom + 10) + ' ' + (-w / 6) + ',' + (bottom - 8) + ' ' + (-w / 2 - 6) + ',' + bottom + ' Z', 'water', 0.75);
      for (var j = 0; j < rows; j++) {
        var pts = [], y = j * 42, off = j % 2 ? 30 : 0;
        for (var x = -w / 2 + off; x <= w / 2; x += 30) pts.push([x, y + ((x + off) / 30 % 2 ? -12 : 12)]);
        s += p(smooth(pts), { w: 6, c: o.color || 'waterLine' });
      }
      return s;
    },
    line: function (o) { var w = o.w || 900; return p('M' + (-w / 2) + ',0 C' + (-w / 6) + ',-6 ' + (w / 6) + ',6 ' + (w / 2) + ',0', { w: o.weight || 6, c: o.color }); },
    hill: function (o) {
      var w = o.w || 420, h = o.h || 160;
      return p('M' + (-w / 2) + ',0 C' + (-w / 3) + ',' + (-h) + ' ' + (w / 4) + ',' + (-h * 1.1) + ' ' + (w / 2) + ',0', { w: 7, c: 'greenLine', fill: o.fill || 'green', fo: 0.9 }) +
        p('M' + (-w * 0.3) + ',' + (-h * 0.35) + ' l14,-14 M' + (-w * 0.22) + ',' + (-h * 0.3) + ' l14,-14 M' + (w * 0.05) + ',' + (-h * 0.5) + ' l14,-14 M' + (w * 0.13) + ',' + (-h * 0.45) + ' l14,-14 M' + (w * 0.3) + ',' + (-h * 0.25) + ' l12,-12', { w: 4, c: 'greenLine', op: 0.6 }) +
        (o.grass === false ? '' : p('M' + (-w * 0.18) + ',' + (-h * 0.78) + ' l-6,-16 M' + (-w * 0.16) + ',' + (-h * 0.8) + ' l4,-18 M' + (w * 0.12) + ',' + (-h * 0.86) + ' l-5,-16 M' + (w * 0.14) + ',' + (-h * 0.86) + ' l5,-15', { w: 5, c: 'greenLine' }));
    },
    cloud: function () {
      return f('M-120,30 C-170,30 -170,-30 -115,-28 C-110,-80 -30,-90 -5,-45 C20,-95 110,-80 105,-20 C160,-20 165,40 110,40 Z', 'cloud', 1, false) +
        f('M-140,10 C-120,22 100,24 150,6 C160,30 140,40 110,40 L-120,30 C-150,30 -160,20 -140,10 Z', 'cloudShade', 0.95) +
        p('M-120,30 C-170,30 -170,-30 -115,-28 C-110,-80 -30,-90 -5,-45 C20,-95 110,-80 105,-20 C160,-20 165,40 110,40 Z', { w: 7 });
    },
    light: function (o) {
      var s = p(wobbleCircle(0, 0, o.r || 80, 7), { c: 'accent', w: 8, fill: 'accent', fo: 0.22 });
      for (var i = 0; i < 16; i++) {
        var a = i / 16 * Math.PI * 2, r1 = (o.r || 80) + 25, r2 = r1 + (i % 2 ? 70 : 130);
        s += p('M' + (Math.cos(a) * r1).toFixed(1) + ',' + (Math.sin(a) * r1).toFixed(1) + ' L' + (Math.cos(a) * r2).toFixed(1) + ',' + (Math.sin(a) * r2).toFixed(1), { c: 'accent', w: 7 });
      }
      return s;
    },
    voice: function (o) {         // sound arcs for "God speaks" (no figure is drawn for God)
      var s = '';
      for (var i = 0; i < 3; i++) { var r = 40 + i * 38; s += p('M' + (r * 0.5).toFixed(0) + ',' + (-r * 0.87).toFixed(0) + ' A' + r + ',' + r + ' 0 0,1 ' + (r * 0.5).toFixed(0) + ',' + (r * 0.87).toFixed(0), { c: 'accent', w: 8 }); }
      return s;
    },
    sun: function () {
      var s = p(wobbleCircle(0, 0, 62, 3), { c: 'accent', w: 8, fill: 'accent', fo: 0.85 });
      for (var i = 0; i < 12; i++) { var a = i / 12 * Math.PI * 2; s += p('M' + (Math.cos(a) * 82).toFixed(1) + ',' + (Math.sin(a) * 82).toFixed(1) + ' L' + (Math.cos(a) * 118).toFixed(1) + ',' + (Math.sin(a) * 118).toFixed(1), { c: 'accent', w: 7 }); }
      return s;
    },
    moon: function () { return p('M20,-60 C-40,-55 -55,40 5,62 C-60,70 -95,-10 -60,-50 C-40,-72 0,-72 20,-60 Z', { w: 7, fill: 'moon', fo: 1 }) + p('M-62,-20 q4,-6 8,0 M-50,20 q4,-5 7,1', { w: 4, c: 'inkSoft' }); },
    star: function (o) { var r = o.r || 22; return p('M0,' + (-r) + ' Q4,-4 ' + r + ',0 Q4,4 0,' + r + ' Q-4,4 ' + (-r) + ',0 Q-4,-4 0,' + (-r) + ' Z', { w: 5, c: o.color, fill: 'starFill', fo: 1 }); },
    stars: function (o) {
      var R = rng(hash(o.id)), n = o.n || 7, w = o.w || 500, h = o.h || 160, s = '';
      for (var i = 0; i < n; i++) {
        var x = -w / 2 + (i + 0.5) * w / n + (R() - 0.5) * 30, y = (R() - 0.5) * h, r = 12 + R() * 12;
        s += '<g class="tw" data-x="' + x.toFixed(0) + '" data-y="' + y.toFixed(0) + '" transform="translate(' + x.toFixed(0) + ',' + y.toFixed(0) + ')">' + OBJ.star({ r: r, color: i === 2 ? 'accent' : 'ink' }) + '</g>';
      }
      return s;
    },
    tree: function () {
      return f('M-12,120 L-9,10 L9,10 L12,120 Z', 'trunk', 0.95) +
        p('M-10,120 L-8,10 M10,120 L8,10 M-8,40 L-40,10 M8,30 L38,0', { w: 7 }) +
        p('M-10,20 C-90,30 -110,-60 -55,-80 C-60,-150 40,-160 50,-100 C110,-100 115,-10 60,5 C40,30 10,25 -10,20 Z', { w: 7, fill: 'leaf', fo: 0.95 }) +
        p('M-50,-40 q10,-12 20,0 M10,-90 q10,-12 20,0 M30,-30 q10,-12 20,0 M-20,-10 q8,-10 16,0', { w: 5, c: 'leafDark' }) +
        f('M-60,128 C-30,118 30,118 60,128 C30,136 -30,136 -60,128 Z', 'shadow', 0.8, false);
    },
    plant: function (o) {
      var s = p('M0,40 C0,10 -4,-10 0,-40', { w: 6, c: 'greenLine' }) + p('M0,0 C-30,-5 -40,-25 -38,-40 C-15,-35 -5,-20 0,0', { w: 5, c: 'greenLine', fill: 'green', fo: 0.9 }) +
        p('M0,-10 C25,-15 38,-35 35,-50 C15,-45 3,-30 0,-10', { w: 5, c: 'greenLine', fill: 'green', fo: 0.9 });
      if (o.flower) s += p(wobbleCircle(0, -52, 14, 11), { c: 'accent', w: 6, fill: 'accent', fo: 0.8 });
      return s;
    },
    fish: function () {
      return f('M-70,0 C-40,-40 30,-40 55,0 C30,40 -40,40 -70,0 Z', 'fishBody', 0.95) + f('M-62,6 C-40,34 30,34 50,6 Z', 'fishBelly', 0.95) +
        p('M-70,0 C-40,-40 30,-40 55,0 C30,40 -40,40 -70,0 Z', { w: 6 }) + p('M55,0 L95,-30 L90,0 L95,30 Z', { w: 6 }) +
        p(circlePath(-40, -6, 5), { w: 5, fill: 'ink' });
    },
    birds: function (o) {
      var n = o.n || 3, s = '';
      for (var i = 0; i < n; i++) {
        var x = i * 90 - (n - 1) * 45, y = (i % 2) * -40, k = 1 - i * 0.12;
        s += p('M' + (x - 40 * k) + ',' + (y - 10) + ' Q' + (x - 18 * k) + ',' + (y - 30 * k) + ' ' + x + ',' + y + ' Q' + (x + 18 * k) + ',' + (y - 30 * k) + ' ' + (x + 40 * k) + ',' + (y - 10), { w: 6 });
      }
      return s;
    },
    animal: function () {     // a sheep: woolly body, head, four legs
      return p('M-80,0 C-110,-10 -100,-60 -60,-55 C-50,-85 0,-90 15,-60 C40,-85 90,-70 80,-35 C110,-20 95,25 60,22 C40,45 -20,45 -40,22 C-80,35 -100,15 -80,0 Z', { w: 6, fill: 'wool', fo: 1 }) +
        p('M80,-35 C105,-55 140,-40 135,-15 C130,5 100,8 88,-5', { w: 6, fill: 'woolGray', fo: 1 }) +
        p('M-50,30 L-52,80 M-20,35 L-18,82 M30,35 L28,82 M55,25 L58,80', { w: 6 }) +
        p('M-55,-25 q8,-10 16,0 M-15,-45 q8,-10 16,0 M25,-30 q8,-10 16,0 M-30,5 q8,-10 16,0 M15,0 q8,-10 16,0', { w: 4, c: 'inkSoft' }) +
        f('M-90,88 C-40,78 40,78 90,88 C40,96 -40,96 -90,88 Z', 'shadow', 0.8, false);
    },
    globe: function (o) {
      var r = o.r || 90;
      return p(wobbleCircle(0, 0, r, 5, 0.03), { w: 7, fill: 'water', fo: 1 }) +
        p('M' + (-r * 0.6) + ',' + (-r * 0.5) + ' C' + (-r * 0.2) + ',' + (-r * 0.75) + ' ' + (r * 0.05) + ',' + (-r * 0.3) + ' ' + (-r * 0.15) + ',' + (-r * 0.05) + ' C' + (-r * 0.35) + ',' + (r * 0.2) + ' ' + (-r * 0.7) + ',' + (r * 0.05) + ' ' + (-r * 0.6) + ',' + (-r * 0.5) + ' Z', { w: 5, c: 'greenLine', fill: 'green', fo: 1 }) +
        p('M' + (r * 0.2) + ',' + (r * 0.15) + ' C' + (r * 0.55) + ',' + (r * 0.05) + ' ' + (r * 0.7) + ',' + (r * 0.4) + ' ' + (r * 0.35) + ',' + (r * 0.65) + ' C' + (r * 0.1) + ',' + (r * 0.55) + ' ' + (r * 0.05) + ',' + (r * 0.3) + ' ' + (r * 0.2) + ',' + (r * 0.15) + ' Z', { w: 5, c: 'greenLine', fill: 'green', fo: 1 });
    },
    figure: function (o) {   // tiny static person icon
      return p(circlePath(0, -70, 18), { w: 6, fill: 'page', fo: 1 }) + p('M0,-52 L0,0 M0,-40 L-24,-18 M0,-40 L24,-18 M0,0 L-18,40 M0,0 L18,40', { w: 6, c: o.color });
    },
    cross: function () { return '<path class="ki-x1" d="" stroke="' + C.accent + '" stroke-width="12" fill="none" stroke-linecap="round"/><path class="ki-x2" d="" stroke="' + C.accent + '" stroke-width="12" fill="none" stroke-linecap="round"/>'; },
    frame: function (o) {     // an empty page / canvas
      var w = (o.w || 700) / 2, h = (o.h || 500) / 2;
      return f('M' + (-w + 12) + ',' + (-h + 12) + ' L' + (w + 12) + ',' + (-h + 12) + ' L' + (w + 12) + ',' + (h + 12) + ' L' + (-w + 12) + ',' + (h + 12) + ' Z', 'shadow', 0.6, false) +
        f('M' + (-w) + ',' + (-h) + ' L' + w + ',' + (-h) + ' L' + w + ',' + h + ' L' + (-w) + ',' + h + ' Z', 'page', 1, false) +
        p('M' + (-w + 14) + ',' + (-h) + ' L' + (w - 10) + ',' + (-h + 4) + ' Q' + w + ',' + (-h) + ' ' + w + ',' + (-h + 14) + ' L' + (w - 4) + ',' + (h - 12) +
        ' Q' + w + ',' + h + ' ' + (w - 14) + ',' + h + ' L' + (-w + 10) + ',' + (h - 3) + ' Q' + (-w) + ',' + h + ' ' + (-w) + ',' + (h - 14) + ' L' + (-w + 3) + ',' + (-h + 12) + ' Q' + (-w) + ',' + (-h) + ' ' + (-w + 14) + ',' + (-h), { w: 6, c: 'inkSoft' });
    },
    dot: function (o) { var r = o.r || 22; return p(wobbleCircle(0, 0, r, 9), { c: o.color || 'accent', w: 6, fill: o.color || 'accent', fo: 1 }); },
    splash: function (o) {    // drops flying up and out (water) or clods (dirt); pops in and fades
      var R = rng(hash(o.id)), n = o.n || 8, r = o.r || 70, s = '', fill = o.dirt ? '#A07850' : 'water', line = o.dirt ? '#6B4A2E' : 'waterLine';
      for (var i = 0; i < n; i++) {
        var a = -Math.PI * (0.1 + 0.8 * i / (n - 1)) + (R() - 0.5) * 0.3, d = r * (0.6 + R() * 0.6);
        var x = Math.cos(a) * d, y = Math.sin(a) * d, k = 7 + R() * 7;
        s += '<g class="spk" transform="translate(' + x.toFixed(0) + ',' + y.toFixed(0) + ')"><g class="spk-i">' +
          p(o.dirt ? wobbleCircle(0, 0, k, i + 3, 0.3) : 'M0,' + (-k * 1.4) + ' C' + (k * 0.9) + ',' + (-k * 0.2) + ' ' + (k * 0.8) + ',' + k + ' 0,' + k + ' C' + (-k * 0.8) + ',' + k + ' ' + (-k * 0.9) + ',' + (-k * 0.2) + ' 0,' + (-k * 1.4) + ' Z',
            { w: 3, c: line, fill: fill, fo: 1 }) + '</g></g>';
      }
      return s;
    },
    sparkle: function (o) {   // a burst of little stars that pops in and fades
      var R = rng(hash(o.id)), n = o.n || 6, r = o.r || 90, s = '';
      for (var i = 0; i < n; i++) {
        var a = i / n * Math.PI * 2 + R() * 0.6, d = r * (0.6 + R() * 0.5), x = Math.cos(a) * d, y = Math.sin(a) * d, k = 10 + R() * 10;
        s += '<g class="spk" transform="translate(' + x.toFixed(0) + ',' + y.toFixed(0) + ')"><g class="spk-i">' +
          p('M0,' + (-k) + ' Q3,-3 ' + k + ',0 Q3,3 0,' + k + ' Q-3,3 ' + (-k) + ',0 Q-3,-3 0,' + (-k) + ' Z', { w: 4, c: i % 2 ? 'accent' : 'ink', fill: 'starFill', fo: 1 }) + '</g></g>';
      }
      return s;
    },
    inset: function (o) {     // a real clip in a hand-drawn, tilted frame (frames swapped per video frame)
      var w = o.w || 380, h = o.h || 260, cid = 'inset-clip-' + o.id, r = 26;
      var rr = 'M' + (-w / 2 + r) + ',' + (-h / 2) + ' L' + (w / 2 - r) + ',' + (-h / 2) + ' Q' + (w / 2) + ',' + (-h / 2) + ' ' + (w / 2) + ',' + (-h / 2 + r) +
        ' L' + (w / 2) + ',' + (h / 2 - r) + ' Q' + (w / 2) + ',' + (h / 2) + ' ' + (w / 2 - r) + ',' + (h / 2) + ' L' + (-w / 2 + r) + ',' + (h / 2) +
        ' Q' + (-w / 2) + ',' + (h / 2) + ' ' + (-w / 2) + ',' + (h / 2 - r) + ' L' + (-w / 2) + ',' + (-h / 2 + r) + ' Q' + (-w / 2) + ',' + (-h / 2) + ' ' + (-w / 2 + r) + ',' + (-h / 2) + ' Z';
      return '<clipPath id="' + cid + '"><path d="' + rr + '"/></clipPath>' +
        '<path d="' + rr + '" transform="translate(12,12)" fill="' + C.shadow + '" stroke="none"/>' +
        '<image class="inset-img" href="' + (o.frames && o.frames[0] || '') + '" x="' + (-w / 2) + '" y="' + (-h / 2) + '" width="' + w + '" height="' + h + '" preserveAspectRatio="xMidYMid slice" clip-path="url(#' + cid + ')"/>' +
        '<path d="' + rr + '" stroke="' + C.ink + '" stroke-width="8" fill="none" stroke-linejoin="round"/>' +
        '<path d="' + rr + '" transform="translate(-4,3) rotate(-0.6)" stroke="' + C.ink + '" stroke-width="3" fill="none" opacity="0.6"/>' +
        '<path d="M-50,' + (-h / 2 - 16) + ' L50,' + (-h / 2 - 10) + ' L46,' + (-h / 2 + 18) + ' L-54,' + (-h / 2 + 12) + ' Z" fill="' + C.marker + '" fill-opacity="0.85" stroke="none"/>';
    },
    scripture: function (o) {   // the channel's signature: quote in handwriting, reference in burnt orange
      var lines = o.lines || [o.text || ''], size = o.size || 76, lh = size * 1.08, w = o.w || 800, pad = 46;
      var refSize = Math.round(size * 0.62), h = pad * 2 + lines.length * lh + refSize * 1.5, top = -h / 2;
      var r = 30, x0 = -w / 2, x1 = w / 2, y0 = top, y1 = top + h;
      var card = 'M' + (x0 + r) + ',' + y0 + ' L' + (x1 - r) + ',' + y0 + ' Q' + x1 + ',' + y0 + ' ' + x1 + ',' + (y0 + r) + ' L' + x1 + ',' + (y1 - r) +
        ' Q' + x1 + ',' + y1 + ' ' + (x1 - r) + ',' + y1 + ' L' + (x0 + r) + ',' + y1 + ' Q' + x0 + ',' + y1 + ' ' + x0 + ',' + (y1 - r) + ' L' + x0 + ',' + (y0 + r) + ' Q' + x0 + ',' + y0 + ' ' + (x0 + r) + ',' + y0 + ' Z';
      var s = '<path d="' + card + '" transform="translate(12,12)" fill="' + C.shadow + '" stroke="none" data-fill="0.9" fill-opacity="0"/>' +
        p(card, { w: 7, fill: 'page', fo: 1 });
      lines.forEach(function (ln, i) {
        var t = (i === 0 ? '\u201C' : '') + ln + (i === lines.length - 1 ? '\u201D' : '');
        s += '<text class="sc-line" x="0" y="' + (top + pad + lh * (i + 0.5)).toFixed(1) + '" text-anchor="middle" dominant-baseline="central" ' +
          'font-family="Caveat" font-weight="700" font-size="' + size + '" fill="' + C.ink + '">' + esc(t) + '</text>';
      });
      var ry = top + pad + lines.length * lh + refSize * 0.55;
      s += '<g class="sc-ref" opacity="0"><g transform="translate(' + (-refSize * 2.9) + ',' + ry.toFixed(1) + ') scale(' + (refSize / 260).toFixed(3) + ')">' + OBJ.book({ ribbon: false }) + '</g>' +
        '<text x="' + (-refSize * 2.0) + '" y="' + ry.toFixed(1) + '" dominant-baseline="central" font-family="Caveat" font-weight="700" font-size="' + refSize + '" fill="' + C.accent + '">' +
        '\u2014 ' + esc(o.ref || '') + '</text></g>';
      return s;
    },
    clock: function (o) {
      var r = o.r || 90;
      return p(wobbleCircle(0, 0, r, 9, 0.02), { w: 8, fill: 'page', fo: 1 }) +
        p('M0,0 L0,' + (-r * 0.62) + ' M0,0 L' + (r * 0.45) + ',' + (r * 0.18), { w: 9 }) +
        p('M0,' + (-r + 12) + ' l0,10 M' + (r - 12) + ',0 l-10,0 M0,' + (r - 12) + ' l0,-10 M' + (-r + 12) + ',0 l10,0', { w: 6, c: 'inkSoft' });
    },
    chair: function () {
      return p('M-40,-110 L-40,60 M-40,0 L45,0 L45,60 M-40,0 L-40,-110 Q-38,-118 -30,-118', { w: 9, c: 'trunk' }) +
        p('M-46,-6 L52,-6 L52,8 L-46,8 Z', { w: 6, fill: 'trunk', fo: 0.9 }) + p('M-40,-100 L-40,-20', { w: 22, c: 'trunk', op: 0.5 });
    },
    check: function (o) { var k = o.k || 1; return p('M' + (-110 * k) + ',' + (-5 * k) + ' L' + (-35 * k) + ',' + (75 * k) + ' L' + (130 * k) + ',' + (-110 * k), { c: 'accent', w: 22 }); },
    arrow: function (o) {
      var x = o.dx == null ? 200 : o.dx, y = o.dy || 0, bend = o.bend == null ? 40 : o.bend, mx = x / 2 - y * bend / 200, my = y / 2 + x * bend / 200;
      var a = Math.atan2(y - my, x - mx), h = 28;
      return p('M0,0 Q' + mx.toFixed(0) + ',' + my.toFixed(0) + ' ' + x + ',' + y, { c: o.color || 'accent', w: 7 }) +
        p('M' + (x - h * Math.cos(a - 0.5)).toFixed(0) + ',' + (y - h * Math.sin(a - 0.5)).toFixed(0) + ' L' + x + ',' + y + ' L' + (x - h * Math.cos(a + 0.5)).toFixed(0) + ',' + (y - h * Math.sin(a + 0.5)).toFixed(0), { c: o.color || 'accent', w: 7 });
    }
  };
  function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

  // ---------------------------------------------------------------- stickman rig
  // Local units: hip at (0,0), y down. Feet touch y = LEG*2 + 6.
  var LEG = 52, TORSO = 95, SHOULDER = 82, UARM = 50, FARM = 48, SH_W = 17;
  var HIP_Y = -(LEG * 2 + 6);
  var V = D.vendor; // vendored upstream SVG snippets: head, expressions, hair

  // Solid "real body" rig: the same joints as the old stick rig (hips, knees, shoulders, elbows),
  // but every part is a filled shape with an ink outline. Simple dot-eye faces (eyebrows only for
  // reactions) and always wears the orange scarf, so he reads as the narrator, never as a created thing.
  var DEFAULT_COLORS = { skin: '#EFD9BC', shirt: '#4A6C8F', pants: '#2F3F52', shoe: '#2B2B2B', hair: '#4A3426', dress: '#C98BA3' };
  function solid(d, fill, w) { return f(d, fill, 1, false) + p(d, { w: w || 4.5 }); }
  function capsule(w0, w1, L) {
    var a = w0 / 2, b = w1 / 2;
    return 'M' + (-a) + ',0 A' + a + ',' + a + ' 0 0 1 ' + a + ',0 L' + b + ',' + L + ' A' + b + ',' + b + ' 0 0 1 ' + (-b) + ',' + L + ' Z';
  }
  function limb(cls, len1, len2, w, color, end) {
    return '<g class="' + cls + '1">' + solid(capsule(w[0], w[1], len1), color) +
      '<g transform="translate(0,' + len1 + ')"><g class="' + cls + '2">' + solid(capsule(w[1], w[2], len2), color) + end +
      '</g></g></g>';
  }
  // Simple faces (every character, same style): two dot eyes and a small mouth, friendly and calm.
  // Head centre (0,-38), radius 33. Eyebrows exist ONLY inside a reaction (under 1.5 s), never angled
  // down toward the middle (never angry).
  function eyes(dx, dy, r) { return p(circlePath(-11 + dx, -42 + dy, r || 3.6) + ' ' + circlePath(11 + dx, -42 + dy, r || 3.6), { w: 2.5, fill: 'ink', fo: 1 }); }
  function mouthO(dx, r) { return p(circlePath(dx || 0, -24, r || 4), { w: 3 }); }
  var FACES = {
    neutral: eyes(0, 0) + p('M-7,-25 Q0,-20 7,-25', { w: 3 }),
    happy: eyes(0, -1) + p('M-10,-27 Q0,-16 10,-27', { w: 3.2 }),
    surprised: eyes(0, -1, 4.2) + mouthO(0, 4.2),
    curious: eyes(4, -2) + p('M-4,-24 Q2,-22 7,-25', { w: 3 }),
    awe: eyes(1, -7) + mouthO(1, 3.6),
    blink: p('M-15,-42 L-7,-42 M7,-42 L15,-42', { w: 3 }) + p('M-7,-25 Q0,-20 7,-25', { w: 3 })
  };
  var FACE_ALIAS = { speaking: 'neutral', thinking: 'curious', focused: 'curious', sad: 'neutral', look_up: 'awe' };
  var RAISED = 'M-19,-55 q7,-6 14,-2 M5,-57 q7,-4 14,2';      // raised brows (surprise / wonder), never angry
  var REACT = {
    puzzled: eyes(3, -3) + p('M-6,-24 L7,-26', { w: 3 }) + p('M-19,-51 L-5,-50 M5,-58 q7,-6 14,1', { w: 4 }) +
      p('M38,-100 q0,-14 12,-14 q12,0 12,12 q0,8 -10,12 l0,8 M50,-66 l0,2', { w: 5, c: 'accent' }),
    surprised: eyes(0, -1, 4.4) + mouthO(0, 4.6) + p(RAISED, { w: 4 }),
    shocked: eyes(0, -1, 4.4) + mouthO(0, 5) + p(RAISED, { w: 4 }) +
      p('M38,-74 C42,-64 44,-58 38,-54 C32,-58 34,-64 38,-74 Z', { w: 3, c: 'waterLine', fill: 'water', fo: 1 }),
    mind_blown: eyes(0, -6) + mouthO(0, 5) + p(RAISED, { w: 4 }) +
      p('M-24,-84 L-36,-106 M-8,-88 L-10,-114 M8,-88 L12,-114 M24,-84 L38,-104', { w: 6, c: 'accent' }),
    side_eye: eyes(6, 0) + p('M-19,-52 L-5,-52 M5,-52 L19,-52', { w: 4 }) + p('M-6,-24 L7,-25', { w: 3 }),
    crying_laughing: p('M-16,-41 q5,-7 10,0 M6,-41 q5,-7 10,0', { w: 3.5 }) + p('M-12,-29 Q0,-12 12,-29 Z', { w: 3, fill: 'ink', fo: 1 }) + p(RAISED, { w: 4 }) +
      p('M-36,-40 C-46,-32 -48,-24 -42,-20 C-36,-24 -36,-32 -36,-40 Z M36,-40 C46,-32 48,-24 42,-20 C36,-24 36,-32 36,-40 Z', { w: 3, c: 'waterLine', fill: 'water', fo: 1 }),
    thinking: eyes(4, -3) + p('M-4,-24 Q2,-22 7,-25', { w: 3 }) + p('M5,-58 q7,-5 14,1', { w: 4 }) +
      p('M36,-98 q0,-14 12,-14 q12,0 12,12 q0,8 -10,12 l0,8 M48,-64 l0,2', { w: 5, c: 'accent' }),
    wait_what: eyes(0, -1, 4) + p('M-6,-24 q3,-3 6,0 q3,3 6,0', { w: 3 }) + p('M-19,-56 q7,-7 14,-2', { w: 4 }) +
      p('M38,-106 q0,-14 11,-14 q11,0 11,11 q0,8 -9,11 l0,7 M49,-76 l0,2', { w: 5, c: 'accent' })
  };
  function buildChar(id, spec) {
    var col = {}; Object.keys(DEFAULT_COLORS).forEach(function (k) { col[k] = (spec.colors || {})[k] || DEFAULT_COLORS[k]; });
    var exprs = '';
    Object.keys(FACES).forEach(function (name) { exprs += '<g class="expr" data-expr="' + name + '" opacity="0">' + FACES[name] + '</g>'; });
    Object.keys(REACT).forEach(function (name) { exprs += '<g class="react" data-react="' + name + '" opacity="0">' + REACT[name] + '</g>'; });
    (D.inboxReactions || []).forEach(function (r) {
      exprs += '<g class="react" data-react="' + r.key + '" opacity="0"><clipPath id="rc-' + id + '-' + r.key + '"><circle cx="0" cy="-38" r="36"/></clipPath>' +
        '<image href="' + r.href + '" x="-38" y="-76" width="76" height="76" preserveAspectRatio="xMidYMid slice" clip-path="url(#rc-' + id + '-' + r.key + ')"/></g>';
    });
    var hairBack = '', hairFront = '';
    if (spec.hair === 'long-straight') {
      hairBack = solid('M-37,-34 C-42,-84 42,-84 37,-34 L38,10 Q30,15 23,8 L22,-28 L-22,-28 L-23,8 Q-30,15 -38,10 Z', col.hair);
      hairFront = solid('M-31,-50 C-22,-76 22,-76 31,-50 C14,-60 -14,-60 -31,-50 Z', col.hair);
    } else if (spec.hair) {
      hairFront = solid('M-32,-46 C-30,-78 30,-78 32,-46 C16,-58 -16,-58 -32,-46 Z', col.hair);
    }
    var torso = solid('M-20,4 C-25,-30 -27,-68 -19,-90 Q0,-100 19,-90 C27,-68 25,-30 20,4 Q0,12 -20,4 Z', col.shirt);
    var dress = spec.dress ? solid('M-21,-46 L-36,16 Q0,26 36,16 L21,-46 Q0,-40 -21,-46 Z', col.dress) : '';
    var scarf = spec.accent ? '<g class="scarf">' + solid('M-18,-92 Q0,-83 18,-92 L19,-80 Q0,-71 -19,-80 Z', C.accent) +
      '<g transform="translate(-7,-79)"><g class="scarfTail">' + solid('M-5,0 C-8,12 -5,24 -9,36 L1,38 C3,26 2,12 5,1 Z', C.accent) + '</g></g></g>' : '';
    var hand = solid(circlePath(0, 4, 8.5), col.skin, 4);
    var shoe = solid('M-9,-4 C-10,6 20,10 25,3 C25,-4 8,-8 -9,-4 Z', col.shoe, 4);
    var leg = function (cls, x) { return '<g transform="translate(' + x + ',0)"><g class="' + cls + '">' + limb(cls, LEG, LEG, [21, 16, 13], col.pants, '<g transform="translate(0,' + (LEG - 2) + ')">' + shoe + '</g>') + '</g></g>'; };
    var arm = function (cls, x, mirror) {
      return '<g transform="translate(' + x + ',-' + SHOULDER + ')"><g class="' + cls + '"' + (mirror ? ' transform="scale(-1,1)"' : '') + '>' +
        limb(cls, UARM, FARM, [16, 13, 11], col.shirt, '<g transform="translate(0,' + FARM + ')">' + hand + '</g>') + '</g></g>';
    };
    // props: parachute above the head, a small snorkel on the face
    var chute = '<g class="chute" opacity="0">' + p('M-36,-180 L-112,-312 M36,-180 L112,-312 M0,-196 L0,-318', { w: 3, c: 'inkSoft' }) +
      solid('M-118,-310 Q0,-450 118,-310 Q88,-296 59,-312 Q30,-296 0,-312 Q-30,-296 -59,-312 Q-88,-296 -118,-310 Z', '#FBF1DC', 5) +
      p('M-59,-312 Q-40,-400 0,-420 M59,-312 Q40,-400 0,-420', { w: 4, c: 'accent' }) + '</g>';
    var snorkel = '<g class="snorkel" opacity="0">' + solid('M-24,-50 Q0,-56 24,-50 L24,-34 Q0,-28 -24,-34 Z', '#BFE3F2', 4) +
      p('M-33,-44 L-24,-43 M24,-43 L33,-44', { w: 4 }) + solid('M30,-40 L36,-40 L36,-100 Q36,-106 30,-106 L30,-40 Z', C.accent, 3.5) + '</g>';
    return '<g class="ki-char" id="char-' + id + '"><clipPath id="cl-' + id + '" clipPathUnits="userSpaceOnUse"><rect class="clipr" x="-600" y="-3000" width="1200" height="3006"/></clipPath>' +
      '<g class="cclip">' +
      '<g class="shadow">' + f('M-46,2 C-24,-7 24,-7 46,2 C24,10 -24,10 -46,2 Z', 'shadow', 0.8, false) + '</g>' +
      '<g class="mover"><g class="flip"><g class="body" transform="translate(0,' + HIP_Y + ')">' + chute +
      leg('legL', -10) + leg('legR', 10) +
      '<g class="torso">' + arm('armL', -SH_W, true) + torso + dress + scarf +
      '<g transform="translate(0,-' + (TORSO - 2) + ')"><g class="head">' + hairBack + solid(circlePath(0, -38, 33), col.skin) + hairFront + exprs + snorkel + '</g></g>' +
      arm('armR', SH_W, false) + '</g>' +
      '</g></g></g></g></g>';
  }

  // ---------------------------------------------------------------- build DOM
  var board = document.getElementById('board');
  var defs = '<defs><filter id="rough" filterUnits="userSpaceOnUse" x="-40" y="-40" width="' + (W + 80) + '" height="' + (H + 80) + '">' +
    '<feTurbulence type="fractalNoise" baseFrequency="0.035" numOctaves="2" seed="4"/>' +
    '<feDisplacementMap in="SourceGraphic" scale="3"/></filter>' +
    '<radialGradient id="glowg"><stop offset="0%" stop-color="#FFF6D8" stop-opacity="1"/><stop offset="45%" stop-color="#FFE7A0" stop-opacity="0.55"/>' +
    '<stop offset="100%" stop-color="#FFE7A0" stop-opacity="0"/></radialGradient>' +
    '<radialGradient id="vig" cx="50%" cy="45%" r="75%"><stop offset="70%" stop-color="#000" stop-opacity="0"/>' +
    '<stop offset="100%" stop-color="#000" stop-opacity="0.07"/></radialGradient></defs>';
  var objMarkup = '', topMarkup = '', charMarkup = '';
  D.objects.forEach(function (o) {
    var fn = OBJ[o.type];
    if (!fn) { console.warn('unknown object type ' + o.type); fn = function () { return ''; }; }
    var mk = '<g class="ki-obj" id="obj-' + o.id + '" data-type="' + o.type + '" transform="translate(' + o.x + ',' + o.y + ') rotate(' + (o.rotate || 0) + ') scale(' + (o.scale || 1) + ')" visibility="hidden">' +
      '<g class="amb"><g class="inner">' + fn(o) + '</g></g></g>';
    if (o.layer === 'top') topMarkup += mk; else objMarkup += mk;     // "top": stays visible on the dark paper
  });
  Object.keys(D.cast).forEach(function (id) { charMarkup += buildChar(id, D.cast[id]); });
  board.innerHTML = defs + '<rect width="' + W + '" height="' + H + '" fill="' + C.board + '"/>' +
    (D.paper ? '<image href="' + D.paper + '" x="0" y="0" width="' + W + '" height="' + H + '" preserveAspectRatio="none"/>' : '') +
    // light that fills the whole scene: warm wash + soft glow + rays spreading out from the source (no spotlight)
    '<g id="light" visibility="hidden"><rect id="lightwash" width="' + W + '" height="' + H + '" fill="#FFF3CF" opacity="0"/>' +
      '<g id="lightsrc"><g id="lightrays"></g><circle id="lightglow" r="900" fill="url(#glowg)" opacity="0"/></g></g>' +
        '<g filter="url(#rough)"><g id="world">' + objMarkup + charMarkup + '<g id="charEnd"/>' +
      '<rect id="darkpaper" x="-6000" y="-6000" width="40000" height="14000" fill="#16141B" opacity="0"/>' + topMarkup + '</g></g>' +
'<g id="wipe" transform="translate(' + (-W - 200) + ',0)"><path d="M0,0 L' + (W + 60) + ',0 C' + (W + 140) + ',' + (H * 0.3) + ' ' + (W + 20) + ',' + (H * 0.6) + ' ' + (W + 120) + ',' + H + ' L0,' + H + ' Z" fill="' + C.board + '" stroke="none"/></g>' +
    '<g id="hud" visibility="hidden" transform="translate(' + D.hud.x + ',' + D.hud.y + ') scale(' + (D.hud.scale || 1) + ')"><g id="hud-in">' +
      '<path d="M-110,-48 L110,-46 Q122,-46 122,-34 L120,40 Q120,52 108,52 L-108,50 Q-120,50 -120,38 L-122,-36 Q-122,-48 -110,-48 Z" fill="' + C.page + '" stroke="' + C.accent + '" stroke-width="6"/>' +
      '<text id="hud-text" x="0" y="-8" text-anchor="middle" dominant-baseline="central" font-family="Caveat" font-weight="700" font-size="60" fill="' + C.ink + '">DAY 1</text>' +
      [0, 1, 2, 3, 4, 5].map(function (i) { return '<circle class="hud-dot" cx="' + (-75 + i * 30) + '" cy="32" r="8" stroke="' + C.accent + '" stroke-width="3" fill="' + C.page + '"/>'; }).join('') +
    '</g></g>' +
    '<rect width="' + W + '" height="' + H + '" fill="url(#vig)" pointer-events="none"/>';
  var world = document.getElementById('world'), charEnd = document.getElementById('charEnd');
  var darkEl = document.getElementById('darkpaper'), lightEl = document.getElementById('light');
  var lightWash = document.getElementById('lightwash'), lightGlow = document.getElementById('lightglow');
  var lightRays = document.getElementById('lightrays'), lightSrc = document.getElementById('lightsrc');
  (function () {
    var s = '';
    for (var i = 0; i < 24; i++) {
      var a = i / 24 * Math.PI * 2, r2 = i % 2 ? 1500 : 1900, w = i % 2 ? 0.05 : 0.08;
      s += '<path d="M0,0 L' + (Math.cos(a - w) * r2).toFixed(0) + ',' + (Math.sin(a - w) * r2).toFixed(0) + ' L' + (Math.cos(a + w) * r2).toFixed(0) + ',' + (Math.sin(a + w) * r2).toFixed(0) + ' Z" fill="#FFE39A" opacity="' + (i % 2 ? 0.35 : 0.5) + '"/>';
    }
    lightRays.innerHTML = s;
  })();

  // Stroke setup: every stroked element draws itself via a normalised dash.
  function prepStrokes(root) {
    var els = root.querySelectorAll('path, circle, line, polyline');
    els.forEach(function (el) {
      if (el.getAttribute('stroke') === 'none' || !el.getAttribute('stroke')) return;
      el.setAttribute('pathLength', '1');
      el.setAttribute('stroke-dasharray', '1 2');
      el.setAttribute('stroke-dashoffset', '1');
    });
    return Array.prototype.filter.call(els, function (el) { return el.hasAttribute('pathLength'); });
  }

  var objs = {};
  D.objects.forEach(function (o) {
    var el = document.getElementById('obj-' + o.id);
    objs[o.id] = { def: o, el: el, inner: el.querySelector('.inner'), mv: { x: 0, y: 0 } };
  });
  function worldBox(id) {     // bbox of an object in world coords
    var ob = objs[id], b = ob.inner.getBBox(), s = ob.def.scale || 1;
    return { x: ob.def.x + b.x * s, y: ob.def.y + b.y * s, w: b.width * s, h: b.height * s };
  }
  // Late geometry (needs fonts): underline, strike, ring, text clip.
  D.objects.forEach(function (o) {
    var ob = objs[o.id], el = ob.el;
    if (o.type === 'word') {
      var t = el.querySelector('text'), b = t.getBBox();
      var cid = 'clip-' + o.id;
      var clip = document.createElementNS(SVGNS, 'clipPath'); clip.id = cid;
      var r = document.createElementNS(SVGNS, 'rect');
      r.setAttribute('x', b.x - 20); r.setAttribute('y', b.y - 20); r.setAttribute('width', 0); r.setAttribute('height', b.height + 40);
      clip.appendChild(r); el.appendChild(clip); t.setAttribute('clip-path', 'url(#' + cid + ')');
      if (o.marker) {            // highlighter band behind the word, revealed with the same wipe
        var mk = document.createElementNS(SVGNS, 'path');
        mk.setAttribute('d', 'M' + (b.x - 12) + ',' + (b.y + b.height * 0.42) + ' L' + (b.x + b.width + 14) + ',' + (b.y + b.height * 0.36) +
          ' L' + (b.x + b.width + 10) + ',' + (b.y + b.height * 0.86) + ' L' + (b.x - 8) + ',' + (b.y + b.height * 0.9) + ' Z');
        mk.setAttribute('fill', C.marker); mk.setAttribute('stroke', 'none'); mk.setAttribute('clip-path', 'url(#' + cid + ')');
        t.parentNode.insertBefore(mk, t);
      }
      ob.clipRect = r; ob.textW = b.width + 40;
      var u = el.querySelector('.ki-underline');
      if (u) u.setAttribute('d', 'M' + (b.x + 10) + ',' + (b.y + b.height * 0.92) + ' C' + (b.x + b.width * 0.4) + ',' + (b.y + b.height * 0.86) + ' ' + (b.x + b.width * 0.7) + ',' + (b.y + b.height * 0.98) + ' ' + (b.x + b.width - 5) + ',' + (b.y + b.height * 0.9));
    }
  });
  D.objects.forEach(function (o) {      // scripture card: one wipe clip per line, written on in order
    if (o.type !== 'scripture') return;
    var ob = objs[o.id];
    ob.lineClips = [];
    ob.el.querySelectorAll('.sc-line').forEach(function (t, i) {
      var b = t.getBBox(), cid = 'clip-' + o.id + '-' + i;
      var clip = document.createElementNS(SVGNS, 'clipPath'); clip.id = cid;
      var r = document.createElementNS(SVGNS, 'rect');
      r.setAttribute('x', b.x - 20); r.setAttribute('y', b.y - 20); r.setAttribute('width', 0); r.setAttribute('height', b.height + 40);
      clip.appendChild(r); ob.el.appendChild(clip); t.setAttribute('clip-path', 'url(#' + cid + ')');
      ob.lineClips.push({ rect: r, w: b.width + 40, n: t.textContent.length });
    });
    ob.refEl = ob.el.querySelector('.sc-ref');
  });
  D.objects.forEach(function (o) {
    var ob = objs[o.id];
    if (o.type === 'cross' && o.target && objs[o.target]) {
      var bb = worldBox(o.target), sc2 = o.scale || 1, m = 10;
      var ax = (bb.x - o.x) / sc2 - m, ay = (bb.y - o.y) / sc2 - m, bx = ax + bb.w / sc2 + 2 * m, by = ay + bb.h / sc2 + 2 * m;
      ob.el.querySelector('.ki-x1').setAttribute('d', 'M' + ax + ',' + ay + ' L' + bx + ',' + by);
      ob.el.querySelector('.ki-x2').setAttribute('d', 'M' + bx + ',' + ay + ' L' + ax + ',' + by);
    }
    if ((o.type === 'strike' || o.type === 'circle') && o.target && objs[o.target]) {
      var b = worldBox(o.target), s = o.scale || 1;
      var x0 = (b.x - o.x) / s, y0 = (b.y - o.y) / s, w = b.w / s, h = b.h / s;
      if (o.type === 'strike') {
        ob.el.querySelector('.ki-strike').setAttribute('d', 'M' + (x0 - 20) + ',' + (y0 + h * 0.62) + ' C' + (x0 + w * 0.3) + ',' + (y0 + h * 0.5) + ' ' + (x0 + w * 0.7) + ',' + (y0 + h * 0.45) + ' ' + (x0 + w + 20) + ',' + (y0 + h * 0.38));
      } else {
        var cx = x0 + w / 2, cy = y0 + h / 2, rx = w / 2 + 40, ry = h / 2 + 30;
        ob.el.querySelector('.ki-ring').setAttribute('d', 'M' + (cx - rx) + ',' + (cy + 10) + ' C' + (cx - rx) + ',' + (cy - ry * 1.3) + ' ' + (cx + rx) + ',' + (cy - ry * 1.3) + ' ' + (cx + rx) + ',' + cy + ' C' + (cx + rx) + ',' + (cy + ry * 1.3) + ' ' + (cx - rx * 0.9) + ',' + (cy + ry * 1.3) + ' ' + (cx - rx * 0.95) + ',' + (cy - 20));
      }
    }
  });
  D.objects.forEach(function (o) { objs[o.id].strokes = prepStrokes(objs[o.id].el); objs[o.id].fills = objs[o.id].el.querySelectorAll('[data-fill]'); });

  // ---------------------------------------------------------------- state
  var cam = { x: D.camera.x, y: D.camera.y, z: D.camera.zoom, r: 0 };
  var chars = {};
  Object.keys(D.cast).forEach(function (id, k) {
    var c = D.cast[id], el = document.getElementById('char-' + id);
    chars[id] = {
      id: id, el: el, flip: el.querySelector('.flip'), body: el.querySelector('.body'), torso: el.querySelector('.torso'),
      head: el.querySelector('.head'), exprEls: el.querySelectorAll('.expr'), reactEls: el.querySelectorAll('.react'),
      mover: el.querySelector('.mover'), cclip: el.querySelector('.cclip'), shadow: el.querySelector('.shadow'),
      clipr: el.querySelector('.clipr'), chute: el.querySelector('.chute'), snorkel: el.querySelector('.snorkel'),
      tail: el.querySelector('.scarfTail'),
      fills: Array.prototype.map.call(el.querySelectorAll('[data-fill]'), function (n) {
        return [n, parseFloat(n.getAttribute('data-fill')), !!n.closest('.scarf')];
      }),
      j: {
        legL1: el.querySelector('.legL1'), legL2: el.querySelector('.legL2'), legR1: el.querySelector('.legR1'), legR2: el.querySelector('.legR2'),
        armL1: el.querySelector('.armL1'), armL2: el.querySelector('.armL2'), armR1: el.querySelector('.armR1'), armR2: el.querySelector('.armR2')
      },
      strokes: prepStrokes(el), scale: c.scale || 1.5, seed: k * 1.7,
      s: {
        x: c.x, y: 0, facing: c.facing || 1, flipX: c.facing || 1, walk: 0, phase: 0, opacity: 1,
        draw: D.events.some(function (e) { return e.do === 'enter' && e.who === id; }) ? 0 : 1,
        armR: 8, armRf: 12, armL: 8, armLf: 12, busyR: 0, busyL: 0, lean: 0, headTilt: 0, legSpread: 0, expr: c.expression || 'neutral',
        reaction: '', rpop: 0,
        lR: 0, lRs: 0, lL: 0, lLs: 0, rotB: 0, ghost: 0, chute: 0, snorkel: 0, swim: 0, swimPh: 0,
        floatAmt: 0, k: c.size || 1, clip: 0, clipY: 0, ride: '', rideDx: 0, rideDy: 0, behind: '', contact: ''
      }
    };
  });

  // ---------------------------------------------------------------- timeline
  var tl = gsap.timeline({ paused: true });
  var hudState = { day: 0, pop: 0 };
  var lightState = { dark: 0, wash: 0, glow: 0, rays: 0, spread: 0.2, x: W / 2, y: H * 0.3 };
  var REST = { armR: 8, armRf: 12, armL: 8, armLf: 12, busyR: 0, busyL: 0, lean: 0, headTilt: 0, legSpread: 0, y: 0,
               lR: 0, lRs: 0, lL: 0, lLs: 0, rotB: 0, floatAmt: 0, swim: 0 };
  var POSE_KEYS = Object.keys(REST);

  var TURN = 0.25;                 // a character turns round BEFORE it starts walking
  function charX(id, t) {        // x of a character at time t (walks are linear)
    var x = D.cast[id].x;
    D.events.forEach(function (e) {
      if (e.who !== id || e.t > t) return;
      if (e.do === 'place' && typeof e.x === 'number') { x = e.x; return; }
      if (e.do === 'climb' && e.dx) { x = e.fromX + e.dx * Math.min(1, (t - e.t) / (e.dur || 1.5)); return; }
      if (e.do === 'drift') { x = e.fromX + (e.to - e.fromX) * Math.min(1, (t - e.t) / (e.dur || 1.5)); return; }
      if (e.do !== 'walk') return;
      var k = Math.max(0, Math.min(1, (t - e.t - e.turn) / e.dur));
      x = e.fromX + (e.to - e.fromX) * k;
    });
    return x;
  }
  // In time order: each walk's start x, duration, and whether it must turn first.
  (function () {
    var pos = {}, facing = {};
    Object.keys(D.cast).forEach(function (id) { pos[id] = D.cast[id].x; facing[id] = D.cast[id].facing || 1; });
    D.events.forEach(function (e) {
      if (!D.cast[e.who]) return;
      if (e.do === 'place' && typeof e.x === 'number') { pos[e.who] = e.x; if (e.facing) facing[e.who] = e.facing; return; }
      if (e.do === 'climb') { e.fromX = pos[e.who]; pos[e.who] += e.dx || 0; return; }
      if (e.do === 'drift') { e.fromX = pos[e.who]; pos[e.who] = e.to; return; }
      if (e.do === 'walk') {
        e.fromX = pos[e.who];
        var dist = Math.abs(e.to - e.fromX), dir = e.to >= e.fromX ? 1 : -1;
        e.dur = e.dur || Math.max(0.6, dist / (e.speed || 420));
        e.turn = dir !== facing[e.who] ? TURN : 0;
        pos[e.who] = e.to;
        facing[e.who] = e.face || dir;
      } else if (e.do === 'face') {
        facing[e.who] = e.facing;
      } else if ((e.do === 'point' || e.do === 'reach') && e.toward) {
        var tx = D.objects.filter(function (o) { return o.id === e.toward; })[0];
        var x = tx ? tx.x : (D.cast[e.toward] ? pos[e.toward] : null);
        if (x != null) facing[e.who] = x >= pos[e.who] ? 1 : -1;
      }
    });
  })();
  function shoulder(id, t) {
    var c = chars[id], sc = c.scale;
    return { x: charX(id, t), y: GROUND + (HIP_Y - SHOULDER) * sc };
  }
  function targetPoint(e) {
    if (e.toward && objs[e.toward]) { var b = worldBox(e.toward); return { x: b.x + b.w / 2, y: b.y + b.h / 2 }; }
    if (e.toward && chars[e.toward]) { return { x: charX(e.toward, e.t), y: GROUND - 200 }; }
    if (typeof e.tx === 'number') return { x: e.tx, y: e.ty };
    return null;
  }
  // Gestures finish with a "rest" tween unless the same character's next
  // gesture starts before then (it continues from the current pose).
  var GESTURES = { point: 1, reach: 1, wave: 1, cheer: 1, react: 1, shrug: 1, present: 1, look: 1, shake: 1, kneel: 1,
    sit: 1, lie_down: 1, swim: 1, float: 1, parachute: 1, pop_up: 1, climb: 1, jump: 1, fall: 1, ride: 1, peek: 1,
    pet: 1, shield_eyes: 1, stand: 1, look_viewer: 1 };
  function pose(s, props, t, dur, ease) {
    var to = {}; Object.keys(props).forEach(function (k) { to[k] = props[k]; });
    to.duration = dur == null ? 0.35 : dur; to.ease = ease || 'power2.inOut';
    tl.to(s, to, t);
  }
  function standUp(s, t, dur) { var r = {}; POSE_KEYS.forEach(function (k) { r[k] = REST[k]; }); pose(s, r, t, dur == null ? 0.4 : dur); }
  // sitting ON the ground: hips at ground level, legs out in front, hands resting on the lap
  var SIT = { lR: 94, lRs: -8, lL: 90, lLs: -4, armR: 30, armRf: 50, armL: 22, armLf: 46, busyR: 1, busyL: 1, lean: -8 };
  var SIT_Y = LEG * 2 + 6 - 12;      // mover offset (x scale) that puts the hips on the ground
  function nextGestureAfter(e) {
    var n = null;
    D.events.forEach(function (o) { if (!n && o !== e && o.who === e.who && GESTURES[o.do] && o.t > e.t) n = o; });
    return n;
  }
  function restAfter(e, s, at, keys) {
    var n = nextGestureAfter(e);
    if (n && n.t <= at + 0.05) return;
    var to = {}; (keys || Object.keys(REST)).forEach(function (k) { to[k] = REST[k]; });
    to.duration = 0.45; to.ease = 'power2.inOut';
    tl.to(s, to, at);
  }
  function face(e, s, tx) {
    var c = charX(e.who, e.t), f = tx >= c ? 1 : -1;
    if (f !== s._facing) { tl.to(s, { flipX: f, duration: 0.22, ease: 'power1.inOut' }, e.t); s._facing = f; }
    return f;
  }
  Object.keys(chars).forEach(function (id) { chars[id].s._facing = chars[id].s.facing; chars[id].s.flipX = chars[id].s.facing; });

  function addDraw(e) {
    var ob = objs[e.id]; if (!ob) return;
    var d = e.dur || ob.def.dur || 1.1;
    tl.set(ob.el, { attr: { visibility: 'visible' } }, e.t);
    if (ob.def.type === 'scripture') {     // card pops in, the quote is written on as it is spoken, then the reference
      tl.set(ob.el, { attr: { visibility: 'visible' } }, Math.max(0, e.t - 0.3));
      var refStrokes = Array.prototype.filter.call(ob.strokes, function (st) { return st.closest('.sc-ref'); });
      var cardStrokes = Array.prototype.filter.call(ob.strokes, function (st) { return !st.closest('.sc-ref'); });
      tl.to(cardStrokes, { attr: { 'stroke-dashoffset': 0 }, duration: 0.3, ease: 'power1.out' }, e.t - 0.3);
      ob.fills.forEach(function (fl) { if (!fl.closest('.sc-ref')) tl.to(fl, { attr: { 'fill-opacity': fl.getAttribute('data-fill') }, duration: 0.25 }, e.t - 0.2); });
      tl.fromTo(ob.inner, { scale: 0.92, transformOrigin: '50% 50%' }, { scale: 1, duration: 0.35, ease: 'back.out(2)', immediateRender: false }, e.t - 0.3);
      var total = ob.lineClips.reduce(function (a, c) { return a + c.n; }, 0) || 1, at = e.t;
      ob.lineClips.forEach(function (c) {
        var ld = d * c.n / total;
        tl.to(c.rect, { attr: { width: c.w }, duration: ld, ease: 'none' }, at);
        at += ld;
      });
      var rt = e.t + d + (e.ref_delay == null ? 0.1 : e.ref_delay);
      tl.set(refStrokes, { attr: { 'stroke-dashoffset': 0 } }, rt);
      ob.fills.forEach(function (fl) { if (fl.closest('.sc-ref')) tl.set(fl, { attr: { 'fill-opacity': fl.getAttribute('data-fill') } }, rt); });
      tl.fromTo(ob.refEl, { attr: { opacity: 0 } }, { attr: { opacity: 1 }, duration: 0.3, immediateRender: false }, rt);
      return;
    }
    if (e.instant) {           // already fully drawn on this frame (hook: frame 0 is never empty)
      if (ob.clipRect) tl.set(ob.clipRect, { attr: { width: ob.textW } }, e.t);
      if (ob.strokes.length) tl.set(ob.strokes, { attr: { 'stroke-dashoffset': 0 } }, e.t);
      ob.fills.forEach(function (f) { tl.set(f, { attr: { 'fill-opacity': f.getAttribute('data-fill') } }, e.t); });
      return;
    }
    if (ob.clipRect) {
      tl.to(ob.clipRect, { attr: { width: ob.textW }, duration: d, ease: 'power1.inOut' }, e.t);
    }
    if (ob.strokes.length) {
      var start = ob.clipRect ? e.t + d * 0.85 : e.t;
      var each = ob.clipRect ? 0.45 : Math.max(0.25, d / Math.max(1, ob.strokes.length * 0.5));
      var stag = ob.strokes.length > 1 ? Math.max(0, (d - each) / (ob.strokes.length - 1)) : 0;
      tl.to(ob.strokes, { attr: { 'stroke-dashoffset': 0 }, duration: each, ease: 'power1.inOut', stagger: stag }, start);
    }
    ob.fills.forEach(function (f) { tl.to(f, { attr: { 'fill-opacity': f.getAttribute('data-fill') }, duration: 0.4 }, e.t + d * 0.8); });
    if (e.pop) tl.fromTo(ob.inner, { scale: 0.55, transformOrigin: '50% 50%' }, { scale: 1, duration: 0.55, ease: 'back.out(2.6)', immediateRender: false }, e.t);
    if (ob.def.type === 'sparkle' || ob.def.type === 'splash') {
      var sp = ob.el.querySelectorAll('.spk-i');
      tl.fromTo(sp, { scale: 0, transformOrigin: '50% 50%' }, { scale: 1, duration: 0.3, ease: 'back.out(3)', stagger: 0.06, immediateRender: false }, e.t);
      tl.to(ob.el, { opacity: 0, duration: 0.35 }, e.t + (e.hold || 1.2));
    }
    if (ob.def.type === 'inset') {
      ob.t0 = e.t; ob.t1 = e.t + (ob.def.clip_dur || 2.2);
      tl.fromTo(ob.inner, { scale: 0.3, rotation: -8, transformOrigin: '50% 50%' }, { scale: 1, rotation: 0, duration: 0.4, ease: 'back.out(2.2)', immediateRender: false }, e.t);
      tl.to(ob.inner, { scale: 0.4, rotation: 6, duration: 0.25, ease: 'back.in(2)' }, ob.t1 - 0.25);
      tl.set(ob.el, { attr: { visibility: 'hidden' } }, ob.t1);
    }
  }

  D.events.forEach(function (e) {
    var c = chars[e.who], s = c && c.s, f, tp;
    switch (e.do) {
      case 'draw': addDraw(e); break;
      case 'place':            // put a character somewhere instantly (used at scene changes)
        tl.set(s, { x: typeof e.x === 'number' ? e.x : s.x, y: e.y || 0, opacity: e.hidden ? 0 : 1, ride: '', behind: '',
                    expr: 'neutral', reaction: '', rpop: 0, clip: 0, chute: 0, snorkel: 0, contact: '' }, e.t);
        if (e.facing) { tl.set(s, { flipX: e.facing }, e.t); s._facing = e.facing; }
        standUp(s, e.t, 0.01);
        break;
      case 'stand': standUp(s, e.t, e.dur); tl.set(s, { ride: '', behind: '', clip: 0, chute: 0, snorkel: 0, contact: '' }, e.t); break;
      case 'look_viewer':
        standUp(s, e.t, 0.4); tl.to(s, { flipX: 1, duration: 0.25 }, e.t); s._facing = 1;
        tl.set(s, { expr: 'neutral', ride: '', behind: '', contact: '' }, e.t);
        break;
      case 'size':             // big + centred for the hook and the last line, small in the scenes
        tl.to(s, { k: e.value || 1, duration: e.dur == null ? 0.6 : e.dur, ease: 'power2.inOut' }, e.t); break;
      case 'drift':            // float across without walking (in the dark, in the air)
        tl.to(s, { x: e.to, duration: e.dur || 1.5, ease: 'sine.inOut' }, e.t); break;
      case 'ghost': tl.to(s, { ghost: e.value == null ? 1 : e.value, duration: e.dur || 0.6 }, e.t); break;
      case 'sit': {            // on the ground; "against": a tree id -> back to the trunk, facing away from it
        var sit = {}; Object.keys(SIT).forEach(function (k) { sit[k] = SIT[k]; });
        sit.y = SIT_Y * c.scale;
        if (e.against && objs[e.against]) {
          var tb = worldBox(e.against), tx = tb.x + tb.w / 2, dir = e.facing || (charX(e.who, e.t) >= tx ? 1 : -1);
          var trunkHalf = 11 * (objs[e.against].def.scale || 1);
          tl.set(s, { x: tx + dir * (trunkHalf + 20 * c.scale), flipX: dir }, e.t); s._facing = dir;
          sit.lean = -4 * 1;
        }
        pose(s, sit, e.t, 0.45);
        tl.set(s, { contact: e.against ? 'tree:' + e.against : 'ground' }, e.t + 0.45);
        if (e.hold) { standUp(s, e.t + e.hold); tl.set(s, { contact: '' }, e.t + e.hold); }
        break;
      }
      case 'lie_down':
        pose(s, { rotB: -90, y: 72 * c.scale, lL: 45, lLs: 85, lR: 4, armR: 165, armRf: 140, armL: 165, armLf: 140, busyR: 1, busyL: 1 }, e.t, 0.6);
        tl.set(s, { contact: 'ground', expr: 'awe' }, e.t + 0.6);
        if (e.hold) { standUp(s, e.t + e.hold, 0.6); tl.set(s, { contact: '', expr: 'neutral' }, e.t + e.hold); }
        break;
      case 'swim': {           // upright-ish crawl: hips below the water line, lower body masked by the water
        var d = e.dur || 2.5, wl = e.in && objs[e.in] ? objs[e.in].def.y : GROUND + (e.y || 0);
        tl.set(s, { snorkel: e.snorkel ? 1 : 0, clip: 1, clipY: wl, opacity: 1 }, e.t);
        tl.set(s, { contact: 'water' }, e.t + 0.4);
        pose(s, { rotB: 28, swim: 1, y: wl - GROUND + 128 * c.scale, busyR: 1, busyL: 1 }, e.t, 0.35);
        tl.to(s, { swimPh: '+=' + (d * 0.9).toFixed(2), duration: d, ease: 'none' }, e.t);
        if (e.dx) tl.to(s, { x: '+=' + e.dx, duration: d, ease: 'sine.inOut' }, e.t);
        if (e.hold !== 0) { tl.set(s, { contact: '' }, e.t + d); standUp(s, e.t + d, 0.4); tl.set(s, { snorkel: 0, clip: 0, clipY: 0 }, e.t + d + 0.4); }
        break;
      }
      case 'float':
        pose(s, { floatAmt: 1, armR: 70, armRf: -5, armL: 70, armLf: -5, lR: 12, lL: -10, busyR: 1, busyL: 1, y: e.y || 0 }, e.t, 0.5);
        if (e.hold) standUp(s, e.t + e.hold, 0.5);
        break;
      case 'parachute': {
        var pd = e.dur || 2.4;
        tl.set(s, { chute: 1, opacity: 1, y: (e.from == null ? -900 : e.from) }, e.t);
        pose(s, { armR: 152, armRf: 10, armL: 152, armLf: 10, busyR: 1, busyL: 1, floatAmt: 0.8, lR: 10, lL: -8 }, e.t, 0.01);
        tl.to(s, { y: e.y || 0, duration: pd, ease: 'sine.out' }, e.t);
        tl.to(s, { chute: 0, floatAmt: 0, duration: 0.45 }, e.t + pd - 0.05);
        standUp(s, e.t + pd + 0.1, 0.4);
        break;
      }
      case 'pop_up':
        tl.set(s, { clip: 1, opacity: 1, y: 260 * c.scale }, e.t);
        tl.to(s, { y: 0, duration: 0.5, ease: 'back.out(2.2)' }, e.t);
        pose(s, { armR: 150, armL: 150, busyR: 1, busyL: 1 }, e.t + 0.2, 0.25, 'back.out(2)');
        tl.set(s, { clip: 0 }, e.t + 0.55);
        standUp(s, e.t + 1.0, 0.35);
        break;
      case 'climb': {
        var cd = e.dur || 1.6, steps = Math.max(2, Math.round(cd / 0.35));
        tl.to(s, { y: '+=' + (e.dy || -120), duration: cd, ease: 'none' }, e.t);
        if (e.dx) tl.to(s, { x: '+=' + e.dx, duration: cd, ease: 'none' }, e.t);
        pose(s, { lean: 14, busyR: 1, busyL: 1 }, e.t, 0.2);
        tl.fromTo(s, { armR: 150, armL: 70, lR: 45, lL: 0 }, { armR: 70, armL: 150, lR: 0, lL: 45, duration: cd / steps, ease: 'sine.inOut',
          yoyo: true, repeat: steps - 1, immediateRender: false }, e.t);
        standUp(s, e.t + cd, 0.3);
        tl.to(s, { y: e.endY == null ? '+=0' : e.endY, duration: 0.01 }, e.t + cd);
        break;
      }
      case 'jump':
        pose(s, { y: 14, lRs: 35, lLs: 35, lR: 18, lL: 18 }, e.t, 0.15);
        tl.to(s, { y: -(e.height || 150), lRs: 0, lLs: 0, lR: 0, lL: 0, armR: 150, armL: 150, busyR: 1, busyL: 1, duration: 0.32, ease: 'power2.out' }, e.t + 0.15);
        tl.to(s, { y: 0, duration: 0.3, ease: 'power2.in' }, e.t + 0.47);
        standUp(s, e.t + 0.78, 0.25);
        break;
      case 'fall': {
        var fd = e.dur || 0.9, sit2 = {}; Object.keys(SIT).forEach(function (k) { sit2[k] = SIT[k]; });
        tl.set(s, { y: -(e.height || 500), opacity: 1 }, e.t);
        tl.fromTo(s, { rotB: 0 }, { rotB: 360, duration: fd, ease: 'power1.in', immediateRender: false }, e.t);
        tl.to(s, { y: 46 * c.scale, duration: fd, ease: 'power2.in' }, e.t);
        tl.set(s, { rotB: 0 }, e.t + fd);
        sit2.y = 46 * c.scale; pose(s, sit2, e.t + fd, 0.15);
        if (e.hold) standUp(s, e.t + fd + e.hold);
        break;
      }
      case 'ride': {           // seated ON the animal: hips on its back, legs down its side, hands holding on
        var ro = objs[e.on], top = ro ? worldBox(e.on).y - ro.def.y : -40;
        tl.set(s, { ride: e.on, rideDx: e.dx || 0, rideDy: e.dy == null ? top + 10 : e.dy, opacity: 1, contact: 'ride:' + e.on }, e.t);
        pose(s, { lR: 78, lRs: 82, lL: 66, lLs: 92, armR: 12, armRf: 34, armL: 8, armLf: 34, busyR: 1, busyL: 1, lean: 10, y: 46 * c.scale }, e.t, 0.01);
        if (e.hold) { standUp(s, e.t + e.hold, 0.3); tl.set(s, { ride: '', contact: '', x: e.offX == null ? s.x : e.offX }, e.t + e.hold); }
        break;
      }
      case 'peek': {
        var po = objs[e.toward]; if (!po) break;
        var side = e.side || 1, bb = worldBox(e.toward);
        tl.set(s, { behind: e.toward, x: bb.x + bb.w / 2, opacity: 1 }, e.t);
        tl.to(s, { x: bb.x + bb.w / 2 + side * (bb.w * 0.42), rotB: side * 16, headTilt: side * 14, duration: 0.45, ease: 'back.out(1.6)' }, e.t);
        tl.set(s, { expr: 'surprised' }, e.t + 0.3);
        if (e.hold) { tl.to(s, { x: bb.x + bb.w / 2 + side * (bb.w * 0.5 + 60), rotB: 0, headTilt: 0, duration: 0.4 }, e.t + e.hold); tl.set(s, { behind: '' }, e.t + e.hold + 0.4); }
        break;
      }
      case 'pet':
        pose(s, { lean: 22, armR: 38, armRf: 8, busyR: 1 }, e.t, 0.3);
        tl.fromTo(s, { armR: 30 }, { armR: 46, duration: 0.25, yoyo: true, repeat: 5, ease: 'sine.inOut', immediateRender: false }, e.t + 0.3);
        tl.set(s, { expr: 'neutral' }, e.t);
        restAfter(e, s, e.t + (e.hold || 1.8));
        break;
      case 'shield_eyes':
        pose(s, { armR: 152, armRf: 118, busyR: 1, lean: -8, headTilt: -10 }, e.t, 0.25);
        tl.set(s, { expr: 'awe' }, e.t);
        restAfter(e, s, e.t + (e.hold || 1.5));
        break;
      case 'splash': break;
      case 'reaction': {
        var rd = Math.min(1.5, e.dur || 1.2);
        tl.set(s, { reaction: e.face }, e.t);
        tl.fromTo(s, { rpop: 0 }, { rpop: 1, duration: 0.18, ease: 'back.out(3)', immediateRender: false }, e.t);
        tl.to(s, { rpop: 0, duration: 0.18 }, e.t + rd - 0.18);
        tl.set(s, { reaction: '' }, e.t + rd);
        break;
      }
      case 'wipe': {
        var wp = document.getElementById('wipe'), wd = e.dur || 0.6;
        tl.fromTo(wp, { x: -W - 200 }, { x: 0, duration: wd / 2, ease: 'power2.in', immediateRender: false }, e.t);
        tl.to(wp, { x: W + 200, duration: wd / 2, ease: 'power2.out' }, e.t + wd / 2);
        break;
      }
      case 'paper':            // dark paper (opening) or normal paper; value 1 = dark
        tl.to(lightState, { dark: e.dark == null ? 1 : e.dark, duration: e.dur || 0.01, ease: 'power1.inOut' }, e.t);
        if (e.dark) tl.to(lightState, { wash: 0, glow: 0, rays: 0, duration: e.dur || 0.01 }, e.t);   // night ends any light burst
        break;
      case 'light_burst': {    // the light fills the whole scene: paper brightens, rays spread from (x, y), soft glow
        var lb = e.dur || 1.2, lh = e.hold || 3.5;
        tl.set(lightState, { x: e.x == null ? W / 2 : e.x, y: e.y == null ? H * 0.3 : e.y }, e.t);
        tl.to(lightState, { dark: 0, duration: lb * 0.6, ease: 'power2.out' }, e.t);
        tl.fromTo(lightState, { wash: 0, glow: 0, rays: 0, spread: 0.15 }, { wash: 0.55, glow: 1, rays: 1, spread: 1, duration: lb, ease: 'power2.out', immediateRender: false }, e.t);
        tl.to(lightState, { wash: 0.12, glow: 0.45, rays: 0.55, duration: 1.0, ease: 'sine.inOut' }, e.t + lb);
        tl.to(lightState, { wash: 0, glow: 0, rays: 0, duration: 1.2, ease: 'sine.inOut' }, e.t + lb + lh);
        break;
      }
      case 'counter':
        tl.set(hudState, { day: e.day }, e.t);
        tl.fromTo(hudState, { pop: 1 }, { pop: 0, duration: 0.55, ease: 'power2.out', immediateRender: false }, e.t);
        break;
      case 'rise':           // a big thing grows up out of the ground (hill, land)
        if (objs[e.id]) tl.fromTo(objs[e.id].inner, { scaleY: 0.02, transformOrigin: '50% 100%' },
          { scaleY: 1, duration: e.dur || 0.9, ease: 'back.out(1.4)', immediateRender: false }, e.t);
        break;
      case 'drop':           // a big thing falls in from above and lands (e.dur = fall time)
        if (objs[e.id]) tl.fromTo(objs[e.id].mv, { y: -(e.height || 1100) }, { y: 0, duration: e.dur || 0.6, ease: 'power2.in', immediateRender: false }, e.t);
        if (objs[e.id]) tl.fromTo(objs[e.id].inner, { scaleY: 0.82, scaleX: 1.12, transformOrigin: '50% 100%' }, { scaleY: 1, scaleX: 1, duration: 0.35, ease: 'back.out(3)', immediateRender: false }, e.t + (e.dur || 0.6));
        break;
      case 'move':           // slide a drawing along (e.g. an animal walking across)
        if (objs[e.id]) tl.to(objs[e.id].mv, { x: e.dx || 0, y: e.dy || 0, duration: e.dur || 2, ease: e.ease || 'none' }, e.t);
        break;
      case 'wiggle':
        if (objs[e.id]) tl.fromTo(objs[e.id].inner, { rotation: -7 }, { rotation: 7, duration: 0.09, yoyo: true, repeat: 5, ease: 'sine.inOut', transformOrigin: '50% 50%', immediateRender: false }, e.t);
        if (objs[e.id]) tl.to(objs[e.id].inner, { rotation: 0, duration: 0.08 }, e.t + 0.55);
        break;
      case 'fade': (e.ids || [e.id]).forEach(function (id) { if (objs[id]) tl.to(objs[id].el, { opacity: e.opacity == null ? 0 : e.opacity, duration: e.dur || 0.5 }, e.t); }); break;
      case 'pulse': if (objs[e.id]) tl.to(objs[e.id].inner, { scale: 1.12, transformOrigin: '50% 50%', duration: 0.25, yoyo: true, repeat: 3, ease: 'sine.inOut' }, e.t); break;
      case 'camera_zoom_out_of':    // zoom transition, first half: punch into the old scene
        tl.to(cam, { z: e.zoom || 1.35, duration: e.dur || 0.3, ease: 'power2.in' }, e.t); break;
      case 'camera':
        tl.to(cam, { x: e.x, y: e.y, z: e.zoom, r: e.rotate || 0, duration: e.dur || 0.8, ease: e.ease || 'power2.inOut' }, e.t); break;
      case 'shake':
        if (!c) { tl.to(cam, { r: 0.6, duration: 0.06, yoyo: true, repeat: 5, ease: 'sine.inOut' }, e.t); break; }
        tl.to(s, { headTilt: 12, duration: 0.14, yoyo: true, repeat: 5, ease: 'sine.inOut' }, e.t);
        tl.set(s, { expr: 'thinking' }, e.t);
        break;
      case 'enter':
        tl.to(s, { draw: 1, duration: e.dur || 1.0, ease: 'power1.inOut' }, e.t);
        break;
      case 'exit': tl.to(s, { opacity: 0, duration: e.dur || 0.4 }, e.t); break;
      case 'express': tl.set(s, { expr: e.expression }, e.t); break;
      case 'face': tl.to(s, { flipX: e.facing, duration: 0.22 }, e.t); s._facing = e.facing; break;
      case 'walk': {
        f = e.to >= e.fromX ? 1 : -1;
        // turn first (in place), then walk forwards
        if (e.turn) tl.fromTo(s, { flipX: -f }, { flipX: f, duration: e.turn, ease: 'power1.inOut', immediateRender: false }, e.t);
        else tl.set(s, { flipX: f }, e.t);
        s._facing = f;
        var t0 = e.t + e.turn, stride = 2 * 80 * c.scale;
        tl.to(s, { x: e.to, duration: e.dur, ease: 'none' }, t0);
        tl.to(s, { phase: '+=' + (Math.abs(e.to - e.fromX) / stride * Math.PI * 2).toFixed(3), duration: e.dur, ease: 'none' }, t0);
        tl.to(s, { walk: 1, duration: 0.2 }, t0);
        tl.to(s, { walk: 0, duration: 0.25 }, t0 + e.dur - 0.12);
        if (e.camera) tl.to(cam, { x: e.camX, y: e.camY == null ? cam.y : e.camY, z: e.camZoom || 1, duration: e.dur + e.turn + 0.2, ease: 'power1.inOut' }, e.t);
        if (e.face && e.face !== f) { tl.to(s, { flipX: e.face, duration: 0.22 }, t0 + e.dur + 0.05); s._facing = e.face; }
        break;
      }
      case 'point': case 'reach': case 'touch': {
        tp = targetPoint(e); if (!tp) break;
        f = face(e, s, tp.x);
        var sh = shoulder(e.who, e.t), dx = (tp.x - sh.x) * f, dy = tp.y - sh.y;
        var ang = Math.atan2(Math.max(dx, 20), dy) * 180 / Math.PI;      // 0 = down, 90 = outward, 180 = up
        var reach = e.do === 'reach' || e.do === 'touch';
        tl.to(s, { armR: ang, armRf: reach ? 0 : 4, busyR: 1, lean: reach ? 7 : 2, duration: 0.35, ease: 'back.out(1.6)' }, e.t);
        tl.set(s, { expr: e.expression || (reach ? 'focused' : 'speaking') }, e.t);
        restAfter(e, s, e.t + (e.hold || 1.5));
        break;
      }
      case 'wave':
        tl.to(s, { armR: 150, armRf: 25, busyR: 1, duration: 0.3 }, e.t);
        tl.to(s, { armRf: -25, duration: 0.22, yoyo: true, repeat: 5, ease: 'sine.inOut' }, e.t + 0.3);
        tl.set(s, { expr: 'happy' }, e.t);
        restAfter(e, s, e.t + 0.3 + 0.22 * 6);
        break;
      case 'cheer':
        tl.to(s, { armR: 135, armRf: -15, armL: 135, armLf: -15, busyR: 1, busyL: 1, duration: 0.3, ease: 'back.out(2)' }, e.t);
        tl.to(s, { y: -38, duration: 0.2, yoyo: true, repeat: 3, ease: 'power1.out' }, e.t);
        tl.set(s, { expr: 'happy' }, e.t);
        restAfter(e, s, e.t + (e.hold || 1.6));
        break;
      case 'react':
        tl.to(s, { armR: 40, armRf: 30, armL: 40, armLf: 30, busyR: 1, busyL: 1, lean: -6, duration: 0.18, ease: 'power2.out' }, e.t);
        tl.to(s, { y: -30, duration: 0.15, yoyo: true, repeat: 1, ease: 'power1.out' }, e.t);
        tl.set(s, { expr: e.expression || 'surprised' }, e.t);
        restAfter(e, s, e.t + (e.hold || 1.2));
        break;
      case 'shrug':
        tl.to(s, { armR: 40, armRf: 75, armL: 40, armLf: 75, busyR: 1, busyL: 1, headTilt: 8, duration: 0.3 }, e.t);
        tl.set(s, { expr: 'thinking' }, e.t);
        restAfter(e, s, e.t + (e.hold || 1.3));
        break;
      case 'present':
        tl.to(s, { armR: 70, armRf: -5, armL: 70, armLf: -5, busyR: 1, busyL: 1, headTilt: -6, duration: 0.35, ease: 'back.out(1.5)' }, e.t);
        tl.set(s, { expr: 'happy' }, e.t);
        restAfter(e, s, e.t + (e.hold || 1.6));
        break;
      case 'look':
        tl.to(s, { headTilt: e.dir === 'down' ? 14 : -16, lean: e.dir === 'down' ? 4 : -4, duration: 0.35 }, e.t);
        if (e.expression) tl.set(s, { expr: e.expression }, e.t);
        restAfter(e, s, e.t + (e.hold || 1.4), ['headTilt', 'lean']);
        break;
      case 'kneel':
        tl.to(s, { legSpread: 1, y: 30, lean: 10, duration: 0.4 }, e.t);
        restAfter(e, s, e.t + (e.hold || 1.6), ['legSpread', 'y', 'lean']);
        break;
    }
  });
  tl.set({}, {}, D.duration);    // timeline spans the whole video

  // ---------------------------------------------------------------- render(t)
  var AMB_XY = {   // the translate part of AMBIENT below, so a rider moves with its animal
    fish: function (t, k) { return [16 * Math.sin(t * 1.5 + k), 4 * Math.sin(t * 3 + k)]; },
    animal: function (t, k) { return [0, -4 * Math.abs(Math.sin(t * 2.2 + k))]; },
    cloud: function (t, k) { return [14 * Math.sin(t * 0.6 + k), 0]; }
  };
  function rot(el, deg) { el.setAttribute('transform', 'rotate(' + deg.toFixed(2) + ')'); }
  function renderChar(c, t) {
    var s = c.s, sc = c.scale * s.k, ph = s.phase, w = s.walk;
    var breath = Math.sin(t * 1.9 + c.seed), sway = Math.sin(t * 1.1 + c.seed);
    var bob = -w * 7 * Math.abs(Math.cos(ph)) - (1 - w) * 2.2 * (breath + 1) / 2;
    var X = s.x, Y = GROUND;
    if (s.ride && objs[s.ride]) {             // riding: follow the object (fish, sheep, cloud...)
      var ro = objs[s.ride];
      var am = AMB_XY[ro.def.type] ? AMB_XY[ro.def.type](t, (hash(s.ride) % 628) / 100) : [0, 0];   // moves with it
      X = ro.def.x + ro.mv.x + s.rideDx + am[0]; Y = ro.def.y + ro.mv.y + s.rideDy + 64 * sc + am[1];   // rideDy = hips, from the object's centre
    }
    var fy = s.floatAmt * 12 * Math.sin(t * 2.2 + c.seed);
    c.el.setAttribute('transform', 'translate(' + X.toFixed(2) + ',' + Y.toFixed(2) + ') scale(' + sc + ')');
    c.mover.setAttribute('transform', 'translate(0,' + ((s.y + fy) / sc).toFixed(2) + ')');
    if (s.clip > 0.5) {        // ground (pop up) or water line (swim) masks the lower body
      c.clipr.setAttribute('height', (3000 + (s.clipY ? (s.clipY - Y) / sc : 6)).toFixed(1));
      c.cclip.setAttribute('clip-path', 'url(#cl-' + c.id + ')');
    } else c.cclip.removeAttribute('clip-path');
    var air = Math.max(0, Math.min(1, 1 + (s.y + fy) / 320));          // shadow shrinks when he is high up
    c.shadow.setAttribute('opacity', (s.ride || s.swim > 0.5 ? 0 : air).toFixed(2));
    c.shadow.setAttribute('transform', 'scale(' + (0.5 + 0.5 * air).toFixed(3) + ',1)');
    c.el.setAttribute('opacity', s.opacity.toFixed(3));
    c.el.setAttribute('visibility', s.draw > 0.001 && s.opacity > 0.001 ? 'visible' : 'hidden');
    c.flip.setAttribute('transform', 'scale(' + (Math.abs(s.flipX) < 0.06 ? 0.06 * Math.sign(s.flipX || 1) : s.flipX).toFixed(3) + ',1)');
    var kneel = s.legSpread, sw = Math.sin(ph);
    var rb = s.rotB + s.floatAmt * 5 * Math.sin(t * 1.3 + c.seed);
    c.body.setAttribute('transform', 'translate(0,' + (HIP_Y + bob).toFixed(2) + ') rotate(' + rb.toFixed(2) + ')');
    // legs (positive lR / lL = swing forward; lRs / lLs = knee bend)
    var flutter = s.swim * 14 * Math.sin(s.swimPh * Math.PI * 4);
    rot(c.j.legR1, -w * 27 * sw - kneel * 70 - s.lR - flutter);
    rot(c.j.legR2, w * 26 * Math.max(0, Math.sin(ph - 0.9)) + w * 6 + kneel * 100 + s.lRs);
    rot(c.j.legL1, w * 27 * sw + kneel * 20 - s.lL + flutter);
    rot(c.j.legL2, w * 26 * Math.max(0, Math.sin(ph + Math.PI - 0.9)) + w * 6 + kneel * 60 + s.lLs);
    c.torso.setAttribute('transform', 'rotate(' + (s.lean + w * 4 + sway * 1.2).toFixed(2) + ')');
    // arms: "outward" angle; swing while walking unless busy; crawl stroke while swimming
    var swingR = w * (1 - s.busyR) * 22 * sw, swingL = -w * (1 - s.busyL) * 22 * sw;
    var idleA = (1 - w) * 2.5 * breath;
    var crawlR = (s.swimPh * 360) % 360, crawlL = (s.swimPh * 360 + 180) % 360;
    var aR = (s.armR + idleA) * (1 - s.swim) + crawlR * s.swim, aL = (s.armL + idleA) * (1 - s.swim) + crawlL * s.swim;
    rot(c.j.armR1, -aR + swingR);
    rot(c.j.armR2, -s.armRf * (1 - s.swim));
    rot(c.j.armL1, -aL - swingL);
    rot(c.j.armL2, -s.armLf * (1 - s.swim));
    var big = 1 + 0.28 * s.rpop, wob = s.reaction ? 6 * Math.sin(t * 22) * s.rpop : 0;
    c.head.setAttribute('transform', 'rotate(' + (s.headTilt + sway * 2.5 + wob).toFixed(2) + ') translate(0,-38) scale(' + big.toFixed(3) + ') translate(0,38)');
    if (c.tail) c.tail.setAttribute('transform', 'rotate(' + (8 * Math.sin(t * 4 + c.seed) + w * 18 + s.chute * 25 + s.swim * 30).toFixed(2) + ')');
    var want = FACES[s.expr] ? s.expr : (FACE_ALIAS[s.expr] || 'neutral');
    var blinking = !s.reaction && (want === 'neutral' || want === 'happy' || want === 'curious') && ((t + c.seed * 2.1) % 3.7) < 0.13;
    var face = s.reaction ? '' : (blinking ? 'blink' : want);
    c.exprEls.forEach(function (g) { g.setAttribute('opacity', g.getAttribute('data-expr') === face && s.draw > 0.6 ? '1' : '0'); });
    c.reactEls.forEach(function (g) { g.setAttribute('opacity', g.getAttribute('data-react') === s.reaction ? '1' : '0'); });
    c.chute.setAttribute('opacity', Math.min(1, s.chute * 1.5).toFixed(3));
    c.chute.setAttribute('transform', 'translate(0,-312) scale(1,' + (0.25 + 0.75 * s.chute).toFixed(3) + ') translate(0,312)');
    c.snorkel.setAttribute('opacity', s.snorkel.toFixed(2));
    // draw-in: strokes in DOM order, then the colour fills (faded right down when he is a "ghost" in the dark)
    var n = c.strokes.length, d = s.draw * (n + 3);
    for (var i = 0; i < n; i++) {
      var k = Math.min(1, Math.max(0, d - i));
      c.strokes[i].setAttribute('stroke-dashoffset', (1 - Math.min(1, k)).toFixed(4));
    }
    c.fills.forEach(function (fl) {
      var o = s.draw > 0.3 ? fl[1] * (fl[2] ? 1 : 1 - 0.88 * s.ghost) : 0;
      fl[0].setAttribute('fill-opacity', o.toFixed(3));
    });
  }


  // captions
  var capEl = document.getElementById('captions');
  var lastChunk = -1;
  function renderCaptions(t) {
    var idx = -1;
    for (var i = 0; i < D.captions.length; i++) { if (t >= D.captions[i].start && t < D.captions[i].end) { idx = i; break; } }
    if (idx !== lastChunk) {
      lastChunk = idx;
      capEl.innerHTML = idx < 0 ? '' : D.captions[idx].words.map(function (w, k) { return '<span data-k="' + k + '">' + esc(w.text) + '</span>'; }).join(' ');
      // shrink to fit the safe box on one line; below the minimum size, wrap instead
      var size = D.captionSize, min = Math.round(size * 0.68);
      capEl.style.whiteSpace = 'nowrap'; capEl.style.fontSize = size + 'px';
      while (size > min && capEl.scrollWidth > capEl.clientWidth) { size -= 4; capEl.style.fontSize = size + 'px'; }
      if (capEl.scrollWidth > capEl.clientWidth) capEl.style.whiteSpace = 'normal';
    }
    if (idx < 0) return;
    var ch = D.captions[idx], spans = capEl.children;
    for (var k = 0; k < spans.length; k++) {
      var w = ch.words[k], active = t >= w.start && (k === spans.length - 1 || t < ch.words[k + 1].start);
      spans[k].className = active ? 'on' : (t >= w.start ? 'said' : '');
    }
    var age = t - ch.start, pop = age < 0.12 ? 0.86 + 0.14 * (age / 0.12) : 1;
    capEl.style.transform = 'translateX(-50%) scale(' + pop.toFixed(3) + ')';
  }


  // ambient motion: every drawing keeps living a little once it is on screen (time-pure)
  var AMBIENT = {
    sun: function (t, k) { return 'rotate(' + (t * 14 % 360).toFixed(2) + ')'; },
    light: function (t, k) { return 'scale(' + (1 + 0.05 * Math.sin(t * 3 + k)).toFixed(4) + ')'; },
    waves: function (t, k) { return 'translate(' + (9 * Math.sin(t * 1.7 + k)).toFixed(2) + ',' + (2 * Math.sin(t * 3.4 + k)).toFixed(2) + ')'; },
    cloud: function (t, k) { return 'translate(' + (14 * Math.sin(t * 0.6 + k)).toFixed(2) + ',0)'; },
    tree: function (t, k) { return 'rotate(' + (2.2 * Math.sin(t * 1.4 + k)).toFixed(2) + ',0,120)'; },
    plant: function (t, k) { return 'rotate(' + (5 * Math.sin(t * 1.9 + k)).toFixed(2) + ',0,40)'; },
    birds: function (t, k) { return 'translate(' + (24 * Math.sin(t * 0.8 + k)).toFixed(2) + ',' + (6 * Math.sin(t * 1.6 + k)).toFixed(2) + ') scale(1,' + (1 + 0.22 * Math.sin(t * 10 + k)).toFixed(3) + ')'; },
    fish: function (t, k) { return 'translate(' + (16 * Math.sin(t * 1.5 + k)).toFixed(2) + ',' + (4 * Math.sin(t * 3 + k)).toFixed(2) + ')'; },
    animal: function (t, k) { return 'translate(0,' + (-4 * Math.abs(Math.sin(t * 2.2 + k))).toFixed(2) + ')'; },
    moon: function (t, k) { return 'rotate(' + (4 * Math.sin(t * 0.9 + k)).toFixed(2) + ')'; },
    globe: function (t, k) { return 'rotate(' + (5 * Math.sin(t * 0.8 + k)).toFixed(2) + ')'; },
    dot: function (t, k) { return 'scale(' + (1 + 0.08 * Math.sin(t * 4 + k)).toFixed(4) + ')'; },
    check: function (t, k) { return 'rotate(' + (2 * Math.sin(t * 2 + k)).toFixed(2) + ')'; },
    figure: function (t, k) { return 'rotate(' + (3 * Math.sin(t * 2.2 + k)).toFixed(2) + ',0,40)'; }
  };
  var ambObjs = Object.keys(objs).map(function (id) {
    var ob = objs[id];
    return { ob: ob, amb: ob.el.querySelector('.amb'), fn: ob.def.still ? null : AMBIENT[ob.def.type], k: (hash(id) % 628) / 100,
             tw: ob.el.querySelectorAll('.tw'), spk: ob.el.querySelectorAll('.spk-i'), img: ob.el.querySelector('.inset-img') };
  });
  var pending = [];
  function renderObjects(t) {
    ambObjs.forEach(function (a) {
      if (a.ob.el.getAttribute('visibility') === 'hidden') return;
      var mv = a.ob.mv, base = (mv.x || mv.y) ? 'translate(' + mv.x.toFixed(2) + ',' + mv.y.toFixed(2) + ') ' : '';
      if (a.fn || base) a.amb.setAttribute('transform', base + (a.fn ? a.fn(t, a.k) : ''));
      a.tw.forEach(function (g, i) {      // stars twinkle one by one
        var sc = 1 + 0.3 * Math.sin(t * 3.2 + i * 1.7 + a.k);
        g.setAttribute('transform', 'translate(' + g.getAttribute('data-x') + ',' + g.getAttribute('data-y') + ') scale(' + sc.toFixed(3) + ') rotate(' + (8 * Math.sin(t * 2 + i)).toFixed(1) + ')');
      });
      if (a.img && a.ob.def.frames && a.ob.t0 != null) {   // real clip: pick this video frame
        var fr = a.ob.def.frames, idx = Math.max(0, Math.min(fr.length - 1, Math.floor((t - a.ob.t0) * (a.ob.def.fps || 30))));
        if (a.img.getAttribute('href') !== fr[idx]) {
          pending.push(new Promise(function (res) {
            var done = function () { a.img.removeEventListener('load', done); a.img.removeEventListener('error', done); res(); };
            a.img.addEventListener('load', done); a.img.addEventListener('error', done); setTimeout(res, 3000);
          }));
          a.img.setAttribute('href', fr[idx]);
        }
      }
    });
  }
  var hud = document.getElementById('hud'), hudIn = document.getElementById('hud-in'), hudText = document.getElementById('hud-text');
  var hudDots = hud.querySelectorAll('.hud-dot');
  function renderHud() {
    hud.setAttribute('visibility', hudState.day > 0 ? 'visible' : 'hidden');
    if (hudState.day <= 0) return;
    hudText.textContent = 'DAY ' + hudState.day;
    hudDots.forEach(function (d, i) { d.setAttribute('fill', i < hudState.day ? C.accent : C.page); });
    hudIn.setAttribute('transform', 'scale(' + (1 + 0.15 * hudState.pop).toFixed(3) + ') rotate(' + (-6 * hudState.pop).toFixed(2) + ')');
  }

  function renderLight(t) {
    var L = lightState;
    darkEl.setAttribute('opacity', (0.9 * L.dark).toFixed(3));
    var on = L.wash > 0.002 || L.glow > 0.002 || L.rays > 0.002;
    lightEl.setAttribute('visibility', on ? 'visible' : 'hidden');
    if (!on) return;
    lightWash.setAttribute('opacity', (0.35 * L.wash).toFixed(3));
    lightGlow.setAttribute('opacity', (0.8 * L.glow).toFixed(3));
    lightSrc.setAttribute('transform', 'translate(' + L.x.toFixed(1) + ',' + L.y.toFixed(1) + ')');
    lightRays.setAttribute('opacity', L.rays.toFixed(3));
    lightRays.setAttribute('transform', 'rotate(' + (t * 4 % 360).toFixed(2) + ') scale(' + L.spread.toFixed(3) + ')');
  }

  var lastOrder = '';
  function render(t) {
    var ids = Object.keys(chars);
    ids.forEach(function (id) { renderChar(chars[id], t); });
    // z-order: a walking character is always in front of everyone else
    var order = ids.slice().sort(function (a, b) { return (chars[a].s.walk > 0.01) - (chars[b].s.walk > 0.01); });
    var key = order.join() + '|' + ids.map(function (id) { return chars[id].s.behind; }).join();
    if (key !== lastOrder) {
      lastOrder = key;
      order.forEach(function (id) {
        var c = chars[id], ob = c.s.behind && objs[c.s.behind];
        if (ob) ob.el.parentNode.insertBefore(c.el, ob.el); else charEnd.parentNode.insertBefore(c.el, charEnd);
      });
    }
    var z = cam.z;
    world.setAttribute('transform', 'translate(' + (W / 2) + ',' + (H / 2) + ') rotate(' + cam.r.toFixed(3) + ') scale(' + z.toFixed(4) + ') translate(' + (-cam.x).toFixed(2) + ',' + (-cam.y).toFixed(2) + ')');
    renderCaptions(t);
    renderObjects(t);
    renderLight(t);
    renderHud();
  }

  var SAFE = D.safe;
  // backdrops / marks meant to sit on or under other drawings
  var NO_OVERLAP_CHECK = { strike: 1, cross: 1, rays: 1, darkness: 1, frame: 1, line: 1, inset: 1, sparkle: 1, splash: 1, circle: 1, light: 1 };
  var transitions = D.events.filter(function (e) { return (e.do === 'walk' && e.camera) || e.transition || e.do === 'wipe'; })
    .map(function (e) { return [e.t - 0.1, e.t + (e.dur || 0.6) + (e.turn || 0) + 0.4]; });
  function inter(a, b) { return Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left)) * Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)); }
  function shown(el) { return el.getAttribute('visibility') !== 'hidden' && parseFloat(getComputedStyle(el).opacity) > 0.3; }
  function glyphBox(ob) {        // a <text> box includes the font's tall line gap: keep the glyph band only
    var r = ob.el.getBoundingClientRect();
    if (ob.def.type !== 'word') return r;
    var top = r.top + r.height * 0.2, bottom = r.bottom - r.height * 0.22;
    return { left: r.left, right: r.right, top: top, bottom: bottom, width: r.width, height: bottom - top };
  }
  function offScreen(r) { var vis = inter(r, { left: 0, top: 0, right: W, bottom: H }); return vis < 0.5 * r.width * r.height; }
  function safeIssues(name, r, out) {
    var tol = 4;
    if (r.left < SAFE.x0 - tol || r.right > SAFE.x1 + tol || r.top < SAFE.y0 - tol || r.bottom > SAFE.y1 + tol) out.push(name + ' outside safe box');
    var cl = SAFE.column;
    if (inter(r, { left: cl.x0 + tol, top: cl.y0 + tol, right: cl.x1, bottom: cl.y1 }) > 0) out.push(name + ' in right button column');
  }
  window.kiCheck = function (t) {
    var out = [], moving = transitions.some(function (w) { return t >= w[0] && t <= w[1]; });
    var words = [], people = [], boxes = {}, covers = [];
    Object.keys(objs).forEach(function (id) {
      var ob = objs[id]; if (!shown(ob.el)) return;
      var r = glyphBox(ob); if (offScreen(r) && !ob.def.offscreen_ok) return;
      if (!moving && !ob.def.offscreen_ok) safeIssues('object ' + id, r, out);
      if (ob.def.type === 'word') words.push([ob.def.text, r]);
      covers.push(r);
    });
    Object.keys(chars).forEach(function (id) {
      var c = chars[id]; if (c.s.draw < 0.05 || !shown(c.el)) return;
      // union of the individual strokes: a group's box of rotated boxes overshoots a lot
      var r = null;
      c.strokes.forEach(function (el) {
        if (el.closest('.expr') || el.closest('.react')) return;
        var prop = el.closest('.chute') || el.closest('.snorkel');
        if (prop && parseFloat(prop.getAttribute('opacity') || '1') < 0.1) return;
        var b = el.getBoundingClientRect();
        if (!b.width && !b.height) return;
        r = r ? { left: Math.min(r.left, b.left), top: Math.min(r.top, b.top), right: Math.max(r.right, b.right), bottom: Math.max(r.bottom, b.bottom) } : { left: b.left, top: b.top, right: b.right, bottom: b.bottom };
      });
      if (!r) return;
      r.width = r.right - r.left; r.height = r.bottom - r.top;
      if (offScreen(r)) return;
      if (!moving) safeIssues(id, r, out);
      boxes[id] = r;
      covers.push(r);
      people.push([id, r, c.s.walk > 0.01]);
    });
    // FILL: the main drawings should cover most of the safe box (grid of 40 px cells, union of boxes)
    if (!moving && D.fillMin) {
      var cell = 40, nx = Math.floor((SAFE.x1 - SAFE.x0) / cell), ny = Math.floor((SAFE.y1 - SAFE.y0) / cell), hit = 0;
      for (var gx = 0; gx < nx; gx++) for (var gy = 0; gy < ny; gy++) {
        var cx = SAFE.x0 + (gx + 0.5) * cell, cy = SAFE.y0 + (gy + 0.5) * cell;
        if (covers.some(function (r) { return cx >= r.left && cx <= r.right && cy >= r.top && cy <= r.bottom; })) hit++;
      }
      window.kiCoverage = hit / (nx * ny);
      if (window.kiCoverage < D.fillMin) out.push('SPARSE FRAME: drawings cover under ' + Math.round(D.fillMin * 100) + '% of the safe box');
    }
    // CONTACT: a pose that touches something (ground, animal, tree, water) must really touch it
    var m = world.getCTM(), sy = function (y) { return m.d * y + m.f; }, sx = function (x) { return m.a * x + m.e; }, tol = 14 * m.d;
    Object.keys(boxes).forEach(function (id) {
      var c = chars[id], ct = c.s.contact, r = boxes[id];
      if (!ct || moving) return;
      if (ct === 'ground' || ct.indexOf('tree:') === 0) {
        var g = sy(GROUND), d = r.bottom - g;
        if (d < -tol) out.push('CONTACT: ' + id + ' floats ' + Math.round(-d) + ' px above the ground');
        if (d > 2 * tol) out.push('CONTACT: ' + id + ' sinks ' + Math.round(d) + ' px into the ground');
      }
      if (ct.indexOf('tree:') === 0 && objs[ct.slice(5)]) {
        var tb = worldBox(ct.slice(5)), cx = sx(tb.x + tb.w / 2), half = 11 * (objs[ct.slice(5)].def.scale || 1) * m.a;
        var gap = Math.min(Math.abs(r.left - cx), Math.abs(r.right - cx)) - half;
        if (gap > tol && !(r.left < cx && r.right > cx)) out.push('CONTACT: ' + id + ' is ' + Math.round(gap) + ' px off the trunk');
      }
      if (ct.indexOf('ride:') === 0 && objs[ct.slice(5)]) {
        var orr = objs[ct.slice(5)].el.getBoundingClientRect();
        if (r.bottom < orr.top + 0.3 * orr.height || r.right < orr.left || r.left > orr.right) out.push('CONTACT: ' + id + ' is not seated on ' + ct.slice(5));
      }
      if (ct === 'water' && c.s.clipY) {
        var hip = sy(GROUND + c.s.y + HIP_Y * c.scale), wl = sy(c.s.clipY);
        if (hip < wl - 4) out.push('CONTACT: ' + id + ' swims on top of the water (hips above the water line)');
        if (r.top > wl) out.push('CONTACT: ' + id + ' is fully under water');
      }
    });
    if (capEl.textContent.trim()) {
      var cr = null, pad = 8;      // real text extent (+ the outline stroke)
      Array.prototype.forEach.call(capEl.children, function (sp) {
        var b = sp.getBoundingClientRect();
        cr = cr ? { left: Math.min(cr.left, b.left), top: Math.min(cr.top, b.top), right: Math.max(cr.right, b.right), bottom: Math.max(cr.bottom, b.bottom) } : { left: b.left, top: b.top, right: b.right, bottom: b.bottom };
      });
      if (cr) safeIssues('captions', { left: cr.left - pad, top: cr.top, right: cr.right + pad, bottom: cr.bottom }, out);
    }
    Object.keys(chars).forEach(function (id) {
      var c = chars[id], vx = charX(id, t + 0.05) - charX(id, t - 0.05);
      if (c.s.walk > 0.3 && Math.abs(vx) > 1 && Math.abs(c.s.flipX) > 0.3 && Math.sign(vx) !== Math.sign(c.s.flipX)) out.push('WALK-FACING: ' + id + ' walks backwards');
    });
    if (!moving) {
      var shownObjs = [];
      Object.keys(objs).forEach(function (id) {
        var ob = objs[id], d = ob.def;
        if (NO_OVERLAP_CHECK[d.type] || d.allow_overlap || !shown(ob.el)) return;
        var r = glyphBox(ob); if (offScreen(r)) return;
        shownObjs.push([id, r, d]);
      });
      if (hudState.day > 0) {
        var hr = hud.getBoundingClientRect();
        safeIssues('DAY counter', hr, out);
        shownObjs.forEach(function (A) { if (A[2].type !== 'inset' && inter(hr, A[1]) > 0) out.push('object ' + A[0] + ' under the DAY counter'); });
      }
      for (var i = 0; i < shownObjs.length; i++) for (var j = i + 1; j < shownObjs.length; j++) {
        var A = shownObjs[i], B = shownObjs[j];
        if (A[2].target === B[0] || B[2].target === A[0] || (A[2].over || []).indexOf(B[0]) >= 0 || (B[2].over || []).indexOf(A[0]) >= 0) continue;
        var small = Math.min(A[1].width * A[1].height, B[1].width * B[1].height);
        if (small > 0 && inter(A[1], B[1]) > 0.1 * small) out.push('object ' + A[0] + ' overlaps ' + B[0]);
      }
    }
    people.forEach(function (pp) {
      words.forEach(function (w) { if (inter(pp[1], w[1]) > 0.04 * w[1].width * w[1].height) out.push(pp[0] + ' covers "' + w[0] + '"'); });
      if (pp[2]) people.forEach(function (q) { if (q !== pp && inter(pp[1], q[1]) > 0.15 * q[1].width * q[1].height) out.push(pp[0] + ' walks through ' + q[0]); });
    });
    return out;
  };
  if (D.debugSafe) {   // overlay the TikTok safe box (debug stills only)
    var ov = document.createElementNS(SVGNS, 'svg');
    ov.setAttribute('viewBox', '0 0 ' + W + ' ' + H); ov.setAttribute('style', 'position:absolute;left:0;top:0;width:' + W + 'px;height:' + H + 'px;pointer-events:none');
    var cl = SAFE.column;
    ov.innerHTML = '<rect x="0" y="0" width="' + W + '" height="' + SAFE.y0 + '" fill="#000" fill-opacity="0.18"/>' +
      '<rect x="0" y="' + SAFE.y1 + '" width="' + W + '" height="' + (H - SAFE.y1) + '" fill="#000" fill-opacity="0.18"/>' +
      '<rect x="' + cl.x0 + '" y="' + cl.y0 + '" width="' + (cl.x1 - cl.x0) + '" height="' + (cl.y1 - cl.y0) + '" fill="#d00" fill-opacity="0.18" stroke="#d00" stroke-width="3"/>' +
      '<rect x="' + SAFE.x0 + '" y="' + SAFE.y0 + '" width="' + (SAFE.x1 - SAFE.x0) + '" height="' + (SAFE.y1 - SAFE.y0) + '" fill="none" stroke="#0a0" stroke-width="4" stroke-dasharray="18 10"/>';
    document.getElementById('stage').appendChild(ov);
  }

  window.kiSeek = function (t) {
    pending = [];
    tl.seek(t, true); render(t);
    return pending.length ? Promise.all(pending).then(function () { return true; }) : true;
  };
  window.kiDuration = D.duration;
  window.kiState = function (id) { var o = {}; var st = chars[id].s; Object.keys(st).forEach(function (k) { o[k] = st[k]; }); return o; };
  window.kiSeek(0);
  window.KI_READY = true;
})();
