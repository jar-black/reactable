PROJ_W = 1920
PROJ_H = 1080
CALIB_W = 1280
CALIB_H = 720
MARKER_SIZE = 130
MARGIN = 160
GRID_COLS = 6
GRID_ROWS = 6
GRID_IDS_START = 4
PLAY_MARGIN_CAM = 80
MIN_MARKER_SPAN = 0.25
MIN_HULL_AREA = 0.02
MIN_PLAY_SIZE = 200

POSITIONS = {}
for row in range(GRID_ROWS):
    y = PROJ_H * (2 * row + 1) // (2 * GRID_ROWS)
    for col in range(GRID_COLS):
        x = PROJ_W * (2 * col + 1) // (2 * GRID_COLS)
        POSITIONS[GRID_IDS_START + row * GRID_COLS + col] = (x, y)


def play_rect():
    return (MARGIN, MARGIN, PROJ_W - MARGIN, PROJ_H - MARGIN)
