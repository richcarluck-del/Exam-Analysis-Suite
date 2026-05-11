def bubble_sort(arr):
    """
    冒泡排序实现
    :param arr: 可排序序列（列表）
    :return: 排序后的新列表
    """
    n = len(arr)
    arr_sorted = arr.copy()
    for i in range(n):
        for j in range(0, n - i - 1):
            if arr_sorted[j] > arr_sorted[j + 1]:
                arr_sorted[j], arr_sorted[j + 1] = arr_sorted[j + 1], arr_sorted[j]
    return arr_sorted

if __name__ == '__main__':
    # 测试代码
    test_cases = [
        [],
        [1],
        [5, 2, 9, 1, 5, 6],
        [3, 2, 1, 0, -1],
        [1, 2, 3, 4, 5],
        [4, 2, 4, 2, 1],
        [10, 9, 8, 7, 6, 5, 4, 3, 2, 1]
    ]
    for idx, case in enumerate(test_cases):
        print(f"Test case {idx+1}: {case}")
        sorted_case = bubble_sort(case)
        print(f"  Sorted     : {sorted_case}")
        print("-" * 30)



