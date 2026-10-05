# Reaction inbox

Your own approved reaction images. Put the file here, add it to `reactions.json`:

```json
{"file": "my_shocked.png", "emotion": "shocked", "approved": true}
```

A scene uses one with `{"at": "Wrong", "do": "reaction", "who": "guide", "emotion": "shocked", "use_inbox": true}`;
the image is cropped to a circle on the character's head for under 1.5 s. Without a matching approved
image, the built-in drawn face for that emotion is used. Remember this repo is public: anything here is public.
