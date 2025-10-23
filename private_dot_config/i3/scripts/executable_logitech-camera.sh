# Fix webcam focus / exposure

export EXTERNAL_CAM=$(v4l2-ctl --list-devices | grep "Logitech Webcam C925e" -A1 | grep dev | awk '{$1=$1};1')

function fixcam_omer {
  v4l2-ctl -d /dev/video0 --set-ctrl=focus_auto=0
  v4l2-ctl -d /dev/video0 --set-ctrl=focus_absolute=0
  v4l2-ctl -d /dev/video0 --set-ctrl=exposure_auto=3
}

function set {
  echo $EXTERNAL_CAM
  v4l2-ctl --device="$EXTERNAL_CAM" --set-ctrl zoom_absolute=100
  v4l2-ctl --device="$EXTERNAL_CAM" --set-ctrl sharpness=150
  v4l2-ctl --device="$EXTERNAL_CAM" --set-ctrl backlight_compensation=1
  v4l2-ctl --device="$EXTERNAL_CAM" --set-ctrl tilt_absolute=0
  v4l2-ctl --device="$EXTERNAL_CAM" --set-ctrl white_balance_automatic=0
  v4l2-ctl --device="$EXTERNAL_CAM" --set-ctrl white_balance_temperature=3000
}

function zoom_1 {
  echo $EXTERNAL_CAM
  v4l2-ctl --device="$EXTERNAL_CAM" --set-ctrl zoom_absolute=135
  v4l2-ctl --device="$EXTERNAL_CAM" --set-ctrl sharpness=150
  v4l2-ctl --device="$EXTERNAL_CAM" --set-ctrl backlight_compensation=1
  v4l2-ctl --device="$EXTERNAL_CAM" --set-ctrl tilt_absolute=-36000
  v4l2-ctl --device="$EXTERNAL_CAM" --set-ctrl white_balance_automatic=1
#  v4l2-ctl --device="$EXTERNAL_CAM" --set-ctrl white_balance_temperature=6500
}

function zoom_2 {
  v4l2-ctl --device="$EXTERNAL_CAM" --set-ctrl zoom_absolute=135
  v4l2-ctl --device="$EXTERNAL_CAM" --set-ctrl sharpness=150
  v4l2-ctl --device="$EXTERNAL_CAM" --set-ctrl backlight_compensation=1
  v4l2-ctl --device="$EXTERNAL_CAM" --set-ctrl tilt_absolute=-10000
  v4l2-ctl --device="$EXTERNAL_CAM" --set-ctrl white_balance_automatic=1
#  v4l2-ctl --device="$EXTERNAL_CAM" --set-ctrl white_balance_temperature=6500

}

function reset {
  v4l2-ctl --device="$EXTERNAL_CAM" --set-ctrl zoom_absolute=100
  v4l2-ctl --device="$EXTERNAL_CAM" --set-ctrl sharpness=128
  v4l2-ctl --device="$EXTERNAL_CAM" --set-ctrl backlight_compensation=0
  v4l2-ctl --device="$EXTERNAL_CAM" --set-ctrl tilt_absolute=0
  v4l2-ctl --device="$EXTERNAL_CAM" --set-ctrl white_balance_automatic=1
#  v4l2-ctl --device="$EXTERNAL_CAM" --set-ctrl white_balance_temperature=4000
}

$1
