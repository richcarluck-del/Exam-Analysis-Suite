
import cv2
import numpy as np
from typing import Dict, List, Tuple

# ... [non_max_suppression and other helpers remain the same] ...

def non_max_suppression(boxes, overlapThresh):
    """手动实现的非极大值抑制。"""
    if len(boxes) == 0: return []
    if boxes.dtype.kind == "i": boxes = boxes.astype("float")
    pick = []
    x1, y1, x2, y2 = boxes[:,0], boxes[:,1], boxes[:,2], boxes[:,3]
    area = (x2 - x1 + 1) * (y2 - y1 + 1)
    idxs = np.argsort(y2)
    while len(idxs) > 0:
        last = len(idxs) - 1
        i = idxs[last]
        pick.append(i)
        xx1 = np.maximum(x1[i], x1[idxs[:last]])
        yy1 = np.maximum(y1[i], y1[idxs[:last]])
        xx2 = np.minimum(x2[i], x2[idxs[:last]])
        yy2 = np.minimum(y2[i], y2[idxs[:last]])
        w = np.maximum(0, xx2 - xx1 + 1)
        h = np.maximum(0, yy2 - yy1 + 1)
        overlap = (w * h) / area[idxs[:last]]
        idxs = np.delete(idxs, np.concatenate(([last], np.where(overlap > overlapThresh)[0])))
    return boxes[pick].astype("int")

def find_template_matches(image: np.ndarray, template: np.ndarray, threshold: float = 0.7) -> List[Tuple[int, int, int, int]]:
    res = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
    loc = np.where(res >= threshold)
    w, h = template.shape[::-1]
    matches = []
    for pt in zip(*loc[::-1]):
        matches.append((pt[0], pt[1], pt[0] + w, pt[1] + h))
    rects = np.array(matches)
    pick = non_max_suppression(rects, overlapThresh=0.3)
    return [tuple(p) for p in pick]

def four_point_transform(image: np.ndarray, pts: np.ndarray) -> np.ndarray:
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    (tl, tr, br, bl) = rect
    widthA = np.sqrt(((br[0] - bl[0]) ** 2) + ((br[1] - bl[1]) ** 2))
    widthB = np.sqrt(((tr[0] - tl[0]) ** 2) + ((tr[1] - tl[1]) ** 2))
    maxWidth = max(int(widthA), int(widthB))
    heightA = np.sqrt(((tr[0] - br[0]) ** 2) + ((tr[1] - br[1]) ** 2))
    heightB = np.sqrt(((tl[0] - bl[0]) ** 2) + ((tl[1] - bl[1]) ** 2))
    maxHeight = max(int(heightA), int(heightB))
    dst = np.array([[0, 0], [maxWidth - 1, 0], [maxWidth - 1, maxHeight - 1], [0, maxHeight - 1]], dtype="float32")
    M = cv2.getPerspectiveTransform(rect, dst)
    return cv2.warpPerspective(image, M, (maxWidth, maxHeight))

def recognize_answer_card(
    image_path: str,
    total_questions: int = 21,
    options_per_question: int = 4,
    num_blocks: int = 5,
    debug: bool = True
) -> Dict[int, str]:
    """
    终极方案V9：修复逻辑错误的最终版。
    """
    # 1. 预处理
    image = cv2.imread(image_path)
    if image is None: raise ValueError(f"无法加载图片：{image_path}")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # 2. 通过轮廓找到整体区域，并进行透视校正
    (T, thresh) = cv2.threshold(cv2.GaussianBlur(gray, (3, 3), 0), 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    cnts, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    bubble_cnts = []
    for c in cnts:
        (x, y, w, h) = cv2.boundingRect(c)
        if (10 <= w <= 40) and (10 <= h <= 30) and (cv2.contourArea(c) / (w*h) > 0.8):
            bubble_cnts.append(c)

    if not bubble_cnts:
        raise RuntimeError("无法在图像中找到任何有效的气泡轮廓。")

    x_coords = [p[0][0] for c in bubble_cnts for p in c]
    y_coords = [p[0][1] for c in bubble_cnts for p in c]
    x_min, x_max = min(x_coords), max(x_coords)
    y_min, y_max = min(y_coords), max(y_coords)

    rect = np.array([(x_min, y_min), (x_max, y_min), (x_max, y_max), (x_min, y_max)], dtype="float32")
    warped = four_point_transform(gray, rect)
    warped_thresh = cv2.threshold(warped, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]

    # 3. 在校正后的图像上进行网格化识别
    total_rows = int(np.ceil(total_questions / num_blocks))
    total_cols = num_blocks * options_per_question
    cell_height = warped_thresh.shape[0] / total_rows
    cell_width = warped_thresh.shape[1] / total_cols

    results = {}
    options = ['A', 'B', 'C', 'D']
    
    # 遍历每一行
    for row_idx in range(total_rows):
        # 遍历每一个题目块 (大列)
        for block_idx in range(num_blocks):
            # 正确计算题号
            q_num = block_idx * total_rows + (row_idx + 1)
            if q_num > total_questions: continue

            densities = []
            # 遍历当前题目的所有选项
            for opt_idx in range(options_per_question):
                col_idx = block_idx * options_per_question + opt_idx
                
                # 计算单元格坐标
                x1 = int(col_idx * cell_width)
                y1 = int(row_idx * cell_height)
                x2 = int((col_idx + 1) * cell_width)
                y2 = int((row_idx + 1) * cell_height)
                
                # 提取单元格ROI并计算像素密度
                cell = warped_thresh[y1:y2, x1:x2]
                density = cv2.countNonZero(cell)
                densities.append(density)

            # 判定答案
            if densities and max(densities) > (cell_width * cell_height * 0.2):
                results[q_num] = options[np.argmax(densities)]
            else:
                results[q_num] = "EMPTY"

    # 4. 可视化调试
    if debug:
        debug_path = image_path.replace('.jpg', '_debug_warp.jpg')
        cv2.imwrite(debug_path, warped_thresh)
        print(f"[INFO] 校正后图像已保存至: {debug_path}")

    return results

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='答题卡识别系统 V9 - 最终修复版')
    parser.add_argument('--image', required=True, help='答题卡图片路径')
    args = parser.parse_args()
    
    print("=" * 60)
    print(f"答题卡识别系统 - V9 (最终修复版)")
    print("=" * 60)
    
    try:
        answers = recognize_answer_card(image_path=args.image)
        print("\n[INFO] 最终识别结果:")
        for q_num in sorted(answers.keys()):
            print(f"  第{q_num:2d}题：{answers[q_num]}")
    except Exception as e:
        print(f"[ERROR] 识别过程中发生错误: {e}")
