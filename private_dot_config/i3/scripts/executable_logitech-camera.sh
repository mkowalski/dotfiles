# Fix webcam focus / exposure

EXTERNAL_CAM=video4

function fixcam_omer {
  v4l2-ctl -d /dev/video0 --set-ctrl=focus_auto=0
  v4l2-ctl -d /dev/video0 --set-ctrl=focus_absolute=0
  v4l2-ctl -d /dev/video0 --set-ctrl=exposure_auto=3
}

function camera_tune {
  v4l2-ctl --device=/dev/$EXTERNAL_CAM --set-ctrl zoom_absolute=135
  v4l2-ctl --device=/dev/$EXTERNAL_CAM --set-ctrl sharpness=150
  v4l2-ctl --device=/dev/$EXTERNAL_CAM --set-ctrl backlight_compensation=1
  v4l2-ctl --device=/dev/$EXTERNAL_CAM --set-ctrl tilt_absolute=-36000
}

function camera_tune2 {
  v4l2-ctl --device=/dev/$EXTERNAL_CAM --set-ctrl zoom_absolute=135
  v4l2-ctl --device=/dev/$EXTERNAL_CAM --set-ctrl sharpness=150
  v4l2-ctl --device=/dev/$EXTERNAL_CAM --set-ctrl backlight_compensation=1
  v4l2-ctl --device=/dev/$EXTERNAL_CAM --set-ctrl tilt_absolute=-10000
}

function camera_reset {
  v4l2-ctl --device=/dev/$EXTERNAL_CAM --set-ctrl zoom_absolute=100
  v4l2-ctl --device=/dev/$EXTERNAL_CAM --set-ctrl sharpness=128
  v4l2-ctl --device=/dev/$EXTERNAL_CAM --set-ctrl backlight_compensation=0
  v4l2-ctl --device=/dev/$EXTERNAL_CAM --set-ctrl tilt_absolute=0
}

$1
