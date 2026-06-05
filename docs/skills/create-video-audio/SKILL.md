---
name: create-video-audio
description: Create and edit videos using Remotion (React/npx — code-driven, best for data viz videos) or moviepy (Python — best for compositing/editing). Audio with ffmpeg-python.
version: "1.0"
trigger_keywords:
  - video
  - audio
  - remotion
  - moviepy
  - ffmpeg
  - mp4
  - mp3
  - animation
  - render video
  - create video
tools_required:
  - write_file
  - run_shell
  - run_python
  - install_package
---

# Creating Videos and Audio Programmatically

Two complementary approaches:

| Tool | Best For | Approach |
|---|---|---|
| **Remotion** | Data-driven videos, animated infographics, personalized content | Write React components, render via `npx remotion` |
| **moviepy** | Video editing, compositing, adding text overlays, screen recording edits | Pure Python |
| **ffmpeg-python** | Format conversion, trimming, compression, batch processing | Python bindings to FFmpeg |

---

## Remotion — React-Based Video Creation (RECOMMENDED for Code-Driven Videos)

Remotion treats video as a React component. The agent writes the component, then renders it.

### Step 1: Create a Remotion Project
```bash
npx create-video@latest --yes --blank my-video-project
cd my-video-project
npm install
```

### Step 2: Write a Video Component
```tsx
// src/MyVideo.tsx
import { AbsoluteFill, Sequence, useCurrentFrame, useVideoConfig, interpolate } from "remotion";

export const MyVideo = ({ title, data }: { title: string; data: number[] }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const opacity = interpolate(frame, [0, 30], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ backgroundColor: "#1e1e2e", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ opacity, color: "white", fontSize: 64, fontWeight: "bold" }}>{title}</div>
      <Sequence from={60}>
        {/* Content appears after 2 seconds (60 frames @ 30fps) */}
        <div style={{ color: "#a78bfa", fontSize: 32 }}>
          {data.map((v, i) => <div key={i}>{v}</div>)}
        </div>
      </Sequence>
    </AbsoluteFill>
  );
};
```

### Step 3: Register Composition (src/Root.tsx)
```tsx
import { Composition } from "remotion";
import { MyVideo } from "./MyVideo";

export const RemotionRoot = () => (
  <Composition
    id="MyVideo"
    component={MyVideo}
    durationInFrames={180}  // 6 seconds at 30fps
    fps={30}
    width={1920}
    height={1080}
    defaultProps={{ title: "Hello World", data: [1, 2, 3] }}
  />
);
```

### Step 4: Render
```bash
# Render with default props
npx remotion render MyVideo --output=out/video.mp4

# Render with custom data (JSON props)
npx remotion render MyVideo \
  --props='{"title": "Q3 Results", "data": [50000, 62000, 75000]}' \
  --output=out/q3_report.mp4

# Render a still frame
npx remotion still MyVideo --frame=30 --output=out/thumbnail.png
```

### Remotion Tips
- Use `interpolate()` for smooth animations tied to frame number
- `useCurrentFrame()` gives you the current frame (0-based)
- `Sequence from={N}` delays component rendering by N frames
- For data-driven videos (charts, text, metrics) — pass everything as props

---

## moviepy — Python Video Editing

```python
# install_package("moviepy")
from moviepy import VideoFileClip, TextClip, CompositeVideoClip, concatenate_videoclips, AudioFileClip
from moviepy.video.fx import FadeIn, FadeOut

# Load and edit existing video
clip = VideoFileClip("input.mp4")
clip = clip.subclipped(10, 30)              # Trim: seconds 10-30
clip = clip.with_effects([FadeIn(1), FadeOut(1)])  # 1-second fade in/out

# Add text overlay
txt = TextClip(
    font="Arial",
    text="MagAgent Demo",
    font_size=60,
    color="white",
    stroke_color="black",
    stroke_width=2,
).with_position(("center", "top")).with_duration(clip.duration)

final = CompositeVideoClip([clip, txt])
final.write_videofile("output.mp4", fps=30, codec="libx264")
```

### Concatenate Clips
```python
clips = [VideoFileClip(f) for f in ["intro.mp4", "main.mp4", "outro.mp4"]]
final = concatenate_videoclips(clips, method="compose")
final.write_videofile("full_video.mp4")
```

### Add Audio
```python
video = VideoFileClip("muted_video.mp4")
audio = AudioFileClip("background.mp3").subclipped(0, video.duration)
final = video.with_audio(audio)
final.write_videofile("with_audio.mp4")
```

---

## ffmpeg-python — Format Conversion and Processing

```python
# install_package("ffmpeg-python")
# Note: also requires ffmpeg binary: sudo apt install ffmpeg
import ffmpeg

# Convert format
ffmpeg.input("input.mov").output("output.mp4").run()

# Trim video
ffmpeg.input("long.mp4", ss=10, t=20).output("trimmed.mp4").run()

# Extract audio
ffmpeg.input("video.mp4").output("audio.mp3").run()

# Compress video
(
    ffmpeg
    .input("raw.mp4")
    .output("compressed.mp4", vcodec="libx264", crf=23, acodec="aac")
    .run()
)

# Create video from images (slideshow)
(
    ffmpeg
    .input("frames/%04d.png", framerate=24)
    .output("slideshow.mp4")
    .run()
)
```

## Decision Guide
```
Video from scratch with animation → Remotion
Edit/composite existing videos   → moviepy
Format conversion, compression   → ffmpeg-python (CLI or python bindings)
Quick GIF from images            → imageio or ffmpeg
```
