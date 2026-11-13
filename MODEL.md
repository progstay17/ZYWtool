# MediaPipe Hand Landmarker model

ZYWtool downloads the official MediaPipe Hand Landmarker model automatically the first time the Hand Check feature is used. No manual model download is required, and the model is not committed to this repository or bundled into the portable ZIP.

- Official Google-hosted model: https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task
- Cache location on Windows: %LOCALAPPDATA%\ZYWtool\models\hand_landmarker.task
- SHA-256 pinned by ZYWtool: fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1

The downloaded file is checked against the pinned SHA-256 before it is atomically installed. Incomplete or mismatched downloads are rejected and removed. If the model is already present but has a different checksum, ZYWtool stops and leaves that file untouched.

The model is a third-party MediaPipe asset distributed under Apache License 2.0. See Google AI Edge MediaPipe and the MediaPipe license:
https://developers.google.com/edge/mediapipe/solutions/vision/hand_landmarker
https://github.com/google-ai-edge/mediapipe/blob/master/LICENSE

An internet connection is required the first time Hand Check is used on each Windows user profile. Other ZYWtool features do not need to download this model.
