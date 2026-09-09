import cv2

DICT_NAME = "DICT_4X4_50"
DEFAULT_DEVICE = "/dev/webcam"


def open_camera(device=DEFAULT_DEVICE, width=1280, height=720, fps=30):
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        print(f"cannot open {device}, trying index 0")
        cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)
    return cap


def make_detector():
    dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, DICT_NAME))
    params = cv2.aruco.DetectorParameters()
    params.detectInvertedMarker = True
    params.adaptiveThreshWinSizeMin = 3
    params.adaptiveThreshWinSizeMax = 31
    params.adaptiveThreshConstant = 7
    params.minMarkerPerimeterRate = 0.02
    params.errorCorrectionRate = 0.8
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_NONE
    return cv2.aruco.ArucoDetector(dictionary, params)


def preprocess(gray):
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    return clahe.apply(gray)
