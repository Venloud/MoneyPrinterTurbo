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
      var s = p('M0,-60 C-60,-80 -140,-78 -190,-55 L-190,70 C-140,48 -60,48 0,70 Z', { fill: 'board', fo: 1 }) +
        p('M0,-60 C60,-80 140,-78 190,-55 L190,70 C140,48 60,48 0,70 Z', { fill: 'board', fo: 1 }) +
        p('M0,-60 L0,70', { w: 6 });
      for (var i = 0; i < 4; i++) {
        var y = -38 + i * 24;
        s += p('M-165,' + (y + 2) + ' C-120,' + (y - 8) + ' -60,' + (y - 8) + ' -25,' + (y + 4), { w: 4, c: 'inkSoft' });
        s += p('M25,' + (y + 4) + ' C60,' + (y - 8) + ' 120,' + (y - 8) + ' 165,' + (y + 2), { w: 4, c: 'inkSoft' });
      }
      if (o.ribbon !== false) s += p('M40,62 L40,120 L55,105 L70,120 L70,60', { c: 'accent', w: 6 });
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
      return p(smooth(pts), { w: 6 });
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
        (o.grass === false ? '' : p('M' + (-w * 0.18) + ',' + (-h * 0.78) + ' l-6,-16 M' + (-w * 0.16) + ',' + (-h * 0.8) + ' l4,-18 M' + (w * 0.12) + ',' + (-h * 0.86) + ' l-5,-16 M' + (w * 0.14) + ',' + (-h * 0.86) + ' l5,-15', { w: 5, c: 'greenLine' }));
    },
    cloud: function () {
      return p('M-120,30 C-170,30 -170,-30 -115,-28 C-110,-80 -30,-90 -5,-45 C20,-95 110,-80 105,-20 C160,-20 165,40 110,40 Z', { w: 7, fill: 'cloud', fo: 0.95 });
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
    moon: function () { return p('M20,-60 C-40,-55 -55,40 5,62 C-60,70 -95,-10 -60,-50 C-40,-72 0,-72 20,-60 Z', { w: 7, fill: 'inkSoft', fo: 0.15 }); },
    star: function (o) { var r = o.r || 22; return p('M0,' + (-r) + ' Q4,-4 ' + r + ',0 Q4,4 0,' + r + ' Q-4,4 ' + (-r) + ',0 Q-4,-4 0,' + (-r) + ' Z', { w: 5, c: o.color }); },
    stars: function (o) {
      var R = rng(hash(o.id)), n = o.n || 7, w = o.w || 500, h = o.h || 160, s = '';
      for (var i = 0; i < n; i++) {
        var x = -w / 2 + (i + 0.5) * w / n + (R() - 0.5) * 30, y = (R() - 0.5) * h, r = 12 + R() * 12;
        s += '<g transform="translate(' + x.toFixed(0) + ',' + y.toFixed(0) + ')">' + OBJ.star({ r: r, color: i === 2 ? 'accent' : 'ink' }) + '</g>';
      }
      return s;
    },
    tree: function () {
      return f('M-12,120 L-9,10 L9,10 L12,120 Z', 'trunk', 0.95) +
        p('M-10,120 L-8,10 M10,120 L8,10 M-8,40 L-40,10 M8,30 L38,0', { w: 7 }) +
        p('M-10,20 C-90,30 -110,-60 -55,-80 C-60,-150 40,-160 50,-100 C110,-100 115,-10 60,5 C40,30 10,25 -10,20 Z', { w: 7, fill: 'leaf', fo: 0.95 });
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
        p('M-50,30 L-52,80 M-20,35 L-18,82 M30,35 L28,82 M55,25 L58,80', { w: 6 });
    },
    globe: function (o) {
      var r = o.r || 90;
      return p(wobbleCircle(0, 0, r, 5, 0.03), { w: 7, fill: 'board', fo: 1 }) +
        p('M' + (-r * 0.6) + ',' + (-r * 0.5) + ' C' + (-r * 0.2) + ',' + (-r * 0.75) + ' ' + (r * 0.05) + ',' + (-r * 0.3) + ' ' + (-r * 0.15) + ',' + (-r * 0.05) + ' C' + (-r * 0.35) + ',' + (r * 0.2) + ' ' + (-r * 0.7) + ',' + (r * 0.05) + ' ' + (-r * 0.6) + ',' + (-r * 0.5) + ' Z', { w: 5, c: 'accent', fill: 'accent', fo: 0.5 }) +
        p('M' + (r * 0.2) + ',' + (r * 0.15) + ' C' + (r * 0.55) + ',' + (r * 0.05) + ' ' + (r * 0.7) + ',' + (r * 0.4) + ' ' + (r * 0.35) + ',' + (r * 0.65) + ' C' + (r * 0.1) + ',' + (r * 0.55) + ' ' + (r * 0.05) + ',' + (r * 0.3) + ' ' + (r * 0.2) + ',' + (r * 0.15) + ' Z', { w: 5, c: 'accent', fill: 'accent', fo: 0.5 });
    },
    figure: function (o) {   // tiny static person icon
      return p(circlePath(0, -70, 18), { w: 6, fill: 'board', fo: 1 }) + p('M0,-52 L0,0 M0,-40 L-24,-18 M0,-40 L24,-18 M0,0 L-18,40 M0,0 L18,40', { w: 6, c: o.color });
    },
    cross: function () { return '<path class="ki-x1" d="" stroke="' + C.accent + '" stroke-width="12" fill="none" stroke-linecap="round"/><path class="ki-x2" d="" stroke="' + C.accent + '" stroke-width="12" fill="none" stroke-linecap="round"/>'; },
    frame: function (o) {     // an empty page / canvas
      var w = (o.w || 700) / 2, h = (o.h || 500) / 2;
      return p('M' + (-w + 14) + ',' + (-h) + ' L' + (w - 10) + ',' + (-h + 4) + ' Q' + w + ',' + (-h) + ' ' + w + ',' + (-h + 14) + ' L' + (w - 4) + ',' + (h - 12) +
        ' Q' + w + ',' + h + ' ' + (w - 14) + ',' + h + ' L' + (-w + 10) + ',' + (h - 3) + ' Q' + (-w) + ',' + h + ' ' + (-w) + ',' + (h - 14) + ' L' + (-w + 3) + ',' + (-h + 12) + ' Q' + (-w) + ',' + (-h) + ' ' + (-w + 14) + ',' + (-h), { w: 6, c: 'inkSoft' });
    },
    dot: function (o) { var r = o.r || 22; return p(wobbleCircle(0, 0, r, 9), { c: o.color || 'accent', w: 6, fill: o.color || 'accent', fo: 1 }); },
    check: function (o) { var k = o.k || 1; return p('M' + (-110 * k) + ',' + (-5 * k) + ' L' + (-35 * k) + ',' + (75 * k) + ' L' + (130 * k) + ',' + (-110 * k), { c: 'accent', w: 22 }); },
    arrow: function (o) {
      var x = o.dx || 200, y = o.dy || 0, bend = o.bend || 40, mx = x / 2 - y * bend / 200, my = y / 2 + x * bend / 200;
      var a = Math.atan2(y - my, x - mx), h = 28;
      return p('M0,0 Q' + mx.toFixed(0) + ',' + my.toFixed(0) + ' ' + x + ',' + y, { c: o.color || 'accent', w: 7 }) +
        p('M' + (x - h * Math.cos(a - 0.5)).toFixed(0) + ',' + (y - h * Math.sin(a - 0.5)).toFixed(0) + ' L' + x + ',' + y + ' L' + (x - h * Math.cos(a + 0.5)).toFixed(0) + ',' + (y - h * Math.sin(a + 0.5)).toFixed(0), { c: o.color || 'accent', w: 7 });
    }
  };
  function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

  // ---------------------------------------------------------------- stickman rig
  // Local units: hip at (0,0), y down. Feet touch y = LEG*2 + 6.
  var LEG = 52, TORSO = 95, SHOULDER = 82, UARM = 50, FARM = 48;
  var HIP_Y = -(LEG * 2 + 6);
  var V = D.vendor; // vendored upstream SVG snippets: head, expressions, hair

  function limb(cls, len1, len2, foot) {
    return '<g class="' + cls + '1">' + p('M0,0 L0,' + len1, { w: 7 }) +
      '<g transform="translate(0,' + len1 + ')"><g class="' + cls + '2">' + p('M0,0 L0,' + len2, { w: 7 }) +
      (foot ? p('M0,' + len2 + ' L13,' + (len2 + 2), { w: 7 }) : p(circlePath(0, len2 + 2, 6), { w: 5, fill: 'board', fo: 1 })) +
      '</g></g></g>';
  }
  function buildChar(id, spec) {
    var exprs = '';
    Object.keys(V.expressions).forEach(function (name) {
      exprs += '<g class="expr" data-expr="' + name + '" transform="translate(0,-39) scale(1.15)" opacity="0">' + V.expressions[name] + '</g>';
    });
    // hair sits BEHIND the head so only the strands outside the face show
    var hair = spec.hair && V.hair[spec.hair] ? '<g transform="translate(0,-74) scale(1.75,1.7)">' + V.hair[spec.hair] + '</g>' : '';
    var accent = spec.accent ? p('M-16,-' + (TORSO - 8) + ' C-6,-' + (TORSO - 18) + ' 6,-' + (TORSO - 18) + ' 16,-' + (TORSO - 8), { c: 'accent', w: 8 }) : '';
    var dress = spec.dress ? p('M0,-' + (TORSO - 20) + ' L-34,8 L34,8 Z', { w: 6, fill: 'accent', fo: 0.35 }) : '';
    var svg =
      '<g class="ki-char" id="char-' + id + '"><g class="flip"><g class="body" transform="translate(0,' + HIP_Y + ')">' +
      '<g class="legL">' + limb('legL', LEG, LEG, true) + '</g>' +
      '<g class="legR">' + limb('legR', LEG, LEG, true) + '</g>' +
      '<g class="torso">' + p('M0,0 L0,-' + TORSO, { w: 7 }) + dress + accent +
      '<g transform="translate(0,-' + SHOULDER + ')"><g class="armL" transform="scale(-1,1)">' + limb('armL', UARM, FARM, false) + '</g></g>' +
      '<g transform="translate(0,-' + SHOULDER + ')"><g class="armR">' + limb('armR', UARM, FARM, false) + '</g></g>' +
      '<g transform="translate(0,-' + (TORSO - 4) + ')"><g class="head">' + V.head + hair + exprs + '</g></g>' +
      '</g></g></g></g>';
    return svg;
  }

  // ---------------------------------------------------------------- build DOM
  var board = document.getElementById('board');
  var defs = '<defs><filter id="rough" x="-5%" y="-5%" width="110%" height="110%">' +
    '<feTurbulence type="fractalNoise" baseFrequency="0.035" numOctaves="2" seed="4"/>' +
    '<feDisplacementMap in="SourceGraphic" scale="3"/></filter>' +
    '<radialGradient id="vig" cx="50%" cy="45%" r="75%"><stop offset="70%" stop-color="#000" stop-opacity="0"/>' +
    '<stop offset="100%" stop-color="#000" stop-opacity="0.07"/></radialGradient></defs>';
  var objMarkup = '', charMarkup = '';
  D.objects.forEach(function (o) {
    var fn = OBJ[o.type];
    if (!fn) { console.warn('unknown object type ' + o.type); fn = function () { return ''; }; }
    objMarkup += '<g class="ki-obj" id="obj-' + o.id + '" data-type="' + o.type + '" transform="translate(' + o.x + ',' + o.y + ') rotate(' + (o.rotate || 0) + ') scale(' + (o.scale || 1) + ')" visibility="hidden">' +
      '<g class="inner">' + fn(o) + '</g></g>';
  });
  Object.keys(D.cast).forEach(function (id) { charMarkup += buildChar(id, D.cast[id]); });
  board.innerHTML = defs + '<rect width="' + W + '" height="' + H + '" fill="' + C.board + '"/>' +
    '<g id="world"><g filter="url(#rough)">' + objMarkup + charMarkup + '</g></g>' +
    '<rect width="' + W + '" height="' + H + '" fill="url(#vig)" pointer-events="none"/>';
  var world = document.getElementById('world');

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
    objs[o.id] = { def: o, el: el, inner: el.querySelector('.inner') };
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
      ob.clipRect = r; ob.textW = b.width + 40;
      var u = el.querySelector('.ki-underline');
      if (u) u.setAttribute('d', 'M' + (b.x + 10) + ',' + (b.y + b.height * 0.92) + ' C' + (b.x + b.width * 0.4) + ',' + (b.y + b.height * 0.86) + ' ' + (b.x + b.width * 0.7) + ',' + (b.y + b.height * 0.98) + ' ' + (b.x + b.width - 5) + ',' + (b.y + b.height * 0.9));
    }
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
      el: el, flip: el.querySelector('.flip'), body: el.querySelector('.body'), torso: el.querySelector('.torso'),
      head: el.querySelector('.head'), exprEls: el.querySelectorAll('.expr'),
      j: {
        legL1: el.querySelector('.legL1'), legL2: el.querySelector('.legL2'), legR1: el.querySelector('.legR1'), legR2: el.querySelector('.legR2'),
        armL1: el.querySelector('.armL1'), armL2: el.querySelector('.armL2'), armR1: el.querySelector('.armR1'), armR2: el.querySelector('.armR2')
      },
      strokes: prepStrokes(el), scale: c.scale || 1.5, seed: k * 1.7,
      s: {
        x: c.x, y: 0, facing: c.facing || 1, flipX: c.facing || 1, walk: 0, phase: 0, opacity: 1,
        draw: D.events.some(function (e) { return e.do === 'enter' && e.who === id; }) ? 0 : 1,
        armR: 8, armRf: 12, armL: 8, armLf: 12, busyR: 0, busyL: 0, lean: 0, headTilt: 0, legSpread: 0, expr: c.expression || 'neutral'
      }
    };
  });

  // ---------------------------------------------------------------- timeline
  var tl = gsap.timeline({ paused: true });
  var REST = { armR: 8, armRf: 12, armL: 8, armLf: 12, busyR: 0, busyL: 0, lean: 0, headTilt: 0, legSpread: 0, y: 0 };

  function charX(id, t) {        // x of a character at time t (walks are linear)
    var x = D.cast[id].x;
    D.events.forEach(function (e) {
      if (e.do !== 'walk' || e.who !== id || e.t > t) return;
      var k = Math.min(1, (t - e.t) / e.dur);
      x = e.fromX + (e.to - e.fromX) * k;
    });
    return x;
  }
  // Fill in each walk's start x and duration in time order.
  (function () {
    var pos = {};
    Object.keys(D.cast).forEach(function (id) { pos[id] = D.cast[id].x; });
    D.events.forEach(function (e) {
      if (e.do !== 'walk') return;
      e.fromX = pos[e.who];
      var dist = Math.abs(e.to - e.fromX);
      e.dur = e.dur || Math.max(0.6, dist / (e.speed || 420));
      pos[e.who] = e.to;
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
  var GESTURES = { point: 1, reach: 1, wave: 1, cheer: 1, react: 1, shrug: 1, present: 1, look: 1, shake: 1, kneel: 1 };
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
    if (e.pop) tl.fromTo(ob.inner, { scale: 0.85, transformOrigin: '50% 50%' }, { scale: 1, duration: 0.5, ease: 'back.out(2)' }, e.t);
  }

  D.events.forEach(function (e) {
    var c = chars[e.who], s = c && c.s, f, tp;
    switch (e.do) {
      case 'draw': addDraw(e); break;
      case 'fade': (e.ids || [e.id]).forEach(function (id) { if (objs[id]) tl.to(objs[id].el, { opacity: e.opacity == null ? 0 : e.opacity, duration: e.dur || 0.5 }, e.t); }); break;
      case 'pulse': if (objs[e.id]) tl.to(objs[e.id].inner, { scale: 1.12, transformOrigin: '50% 50%', duration: 0.25, yoyo: true, repeat: 3, ease: 'sine.inOut' }, e.t); break;
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
        if (f !== s._facing) { tl.to(s, { flipX: f, duration: 0.2 }, e.t); s._facing = f; }
        var stride = 2 * 80 * c.scale;
        tl.to(s, { x: e.to, duration: e.dur, ease: 'none' }, e.t);
        tl.to(s, { phase: '+=' + (Math.abs(e.to - e.fromX) / stride * Math.PI * 2).toFixed(3), duration: e.dur, ease: 'none' }, e.t);
        tl.to(s, { walk: 1, duration: 0.2 }, e.t);
        tl.to(s, { walk: 0, duration: 0.25 }, e.t + e.dur - 0.12);
        if (e.camera) tl.to(cam, { x: e.camX, y: e.camY == null ? cam.y : e.camY, z: e.camZoom || 1, duration: e.dur + 0.2, ease: 'power1.inOut' }, e.t);
        if (e.face) tl.to(s, { flipX: e.face, duration: 0.22 }, e.t + e.dur); if (e.face) s._facing = e.face;
        break;
      }
      case 'point': case 'reach': {
        tp = targetPoint(e); if (!tp) break;
        f = face(e, s, tp.x);
        var sh = shoulder(e.who, e.t), dx = (tp.x - sh.x) * f, dy = tp.y - sh.y;
        var ang = Math.atan2(Math.max(dx, 20), dy) * 180 / Math.PI;      // 0 = down, 90 = outward, 180 = up
        var reach = e.do === 'reach';
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
  function rot(el, deg) { el.setAttribute('transform', 'rotate(' + deg.toFixed(2) + ')'); }
  function renderChar(c, t) {
    var s = c.s, sc = c.scale, ph = s.phase, w = s.walk;
    var breath = Math.sin(t * 1.9 + c.seed), sway = Math.sin(t * 1.1 + c.seed);
    var bob = -w * 7 * Math.abs(Math.cos(ph)) - (1 - w) * 2.2 * (breath + 1) / 2;
    c.el.setAttribute('transform', 'translate(' + s.x.toFixed(2) + ',' + (GROUND + s.y).toFixed(2) + ') scale(' + sc + ')');
    c.el.setAttribute('opacity', s.opacity.toFixed(3));
    c.el.setAttribute('visibility', s.draw > 0.001 && s.opacity > 0.001 ? 'visible' : 'hidden');
    c.flip.setAttribute('transform', 'scale(' + (Math.abs(s.flipX) < 0.06 ? 0.06 * Math.sign(s.flipX || 1) : s.flipX).toFixed(3) + ',1)');
    var kneel = s.legSpread;
    c.body.setAttribute('transform', 'translate(0,' + (HIP_Y + bob).toFixed(2) + ')');
    // legs (positive rotation swings a leg backward when facing right)
    var sw = Math.sin(ph);
    rot(c.j.legR1, -w * 27 * sw - kneel * 70);
    rot(c.j.legR2, w * 26 * Math.max(0, Math.sin(ph - 0.9)) + w * 6 + kneel * 100);
    rot(c.j.legL1, w * 27 * sw + kneel * 20);
    rot(c.j.legL2, w * 26 * Math.max(0, Math.sin(ph + Math.PI - 0.9)) + w * 6 + kneel * 60);
    // torso lean + breathing
    c.torso.setAttribute('transform', 'rotate(' + (s.lean + w * 4 + sway * 1.2).toFixed(2) + ')');
    // arms: "outward" angle; swing while walking unless busy
    var swingR = w * (1 - s.busyR) * 22 * sw, swingL = -w * (1 - s.busyL) * 22 * sw;
    var idleA = (1 - w) * 2.5 * breath;
    rot(c.j.armR1, -(s.armR + idleA) + swingR);
    rot(c.j.armR2, -s.armRf);
    rot(c.j.armL1, -(s.armL + idleA) - swingL);
    rot(c.j.armL2, -s.armLf);
    c.head.setAttribute('transform', 'rotate(' + (s.headTilt + sway * 2.5).toFixed(2) + ')');
    c.exprEls.forEach(function (g) { g.setAttribute('opacity', g.getAttribute('data-expr') === s.expr && s.draw > 0.6 ? '1' : '0'); });
    // draw-in: strokes in DOM order
    var n = c.strokes.length, d = s.draw * (n + 3);
    for (var i = 0; i < n; i++) {
      var k = Math.min(1, Math.max(0, d - i));
      c.strokes[i].setAttribute('stroke-dashoffset', (1 - Math.min(1, k)).toFixed(4));
    }
    var heads = c.el.querySelectorAll('[data-fill]');
    heads.forEach(function (h) { h.setAttribute('fill-opacity', s.draw > 0.3 ? h.getAttribute('data-fill') : 0); });
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

  var lastOrder = '';
  function render(t) {
    var ids = Object.keys(chars);
    ids.forEach(function (id) { renderChar(chars[id], t); });
    // z-order: a walking character is always in front of everyone else
    var order = ids.slice().sort(function (a, b) { return (chars[a].s.walk > 0.01) - (chars[b].s.walk > 0.01); });
    if (order.join() !== lastOrder) {
      lastOrder = order.join();
      order.forEach(function (id) { chars[id].el.parentNode.appendChild(chars[id].el); });
    }
    var z = cam.z;
    world.setAttribute('transform', 'translate(' + (W / 2) + ',' + (H / 2) + ') rotate(' + cam.r.toFixed(3) + ') scale(' + z.toFixed(4) + ') translate(' + (-cam.x).toFixed(2) + ',' + (-cam.y).toFixed(2) + ')');
    renderCaptions(t);
  }

  var SAFE = D.safe;
  var transitions = D.events.filter(function (e) { return e.do === 'walk' && e.camera; }).map(function (e) { return [e.t, e.t + e.dur + 0.3]; });
  function inter(a, b) { return Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left)) * Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)); }
  function shown(el) { return el.getAttribute('visibility') !== 'hidden' && parseFloat(getComputedStyle(el).opacity) > 0.3; }
  function offScreen(r) { var vis = inter(r, { left: 0, top: 0, right: W, bottom: H }); return vis < 0.5 * r.width * r.height; }
  function safeIssues(name, r, out) {
    var tol = 4;
    if (r.left < SAFE.x0 - tol || r.right > SAFE.x1 + tol || r.top < SAFE.y0 - tol || r.bottom > SAFE.y1 + tol) out.push(name + ' outside safe box');
    var cl = SAFE.column;
    if (inter(r, { left: cl.x0 + tol, top: cl.y0 + tol, right: cl.x1, bottom: cl.y1 }) > 0) out.push(name + ' in right button column');
  }
  window.kiCheck = function (t) {
    var out = [], moving = transitions.some(function (w) { return t >= w[0] && t <= w[1]; });
    var words = [], people = [];
    Object.keys(objs).forEach(function (id) {
      var ob = objs[id]; if (!shown(ob.el)) return;
      var r = ob.el.getBoundingClientRect(); if (offScreen(r)) return;
      if (!moving) safeIssues('object ' + id, r, out);
      if (ob.def.type === 'word') words.push([ob.def.text, r]);
    });
    Object.keys(chars).forEach(function (id) {
      var c = chars[id]; if (c.s.draw < 0.05 || !shown(c.el)) return;
      // union of the individual strokes: a group's box of rotated boxes overshoots a lot
      var r = null;
      c.strokes.forEach(function (el) {
        if (el.closest('.expr')) return;
        var b = el.getBoundingClientRect();
        if (!b.width && !b.height) return;
        r = r ? { left: Math.min(r.left, b.left), top: Math.min(r.top, b.top), right: Math.max(r.right, b.right), bottom: Math.max(r.bottom, b.bottom) } : { left: b.left, top: b.top, right: b.right, bottom: b.bottom };
      });
      if (!r) return;
      r.width = r.right - r.left; r.height = r.bottom - r.top;
      if (offScreen(r)) return;
      if (!moving) safeIssues(id, r, out);
      people.push([id, r, c.s.walk > 0.01]);
    });
    if (capEl.textContent.trim()) safeIssues('captions', capEl.getBoundingClientRect(), out);
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

  window.kiSeek = function (t) { tl.seek(t, true); render(t); return true; };
  window.kiDuration = D.duration;
  window.kiSeek(0);
  window.KI_READY = true;
})();
