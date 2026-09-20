#!/home/user/.venv/bin/python3
"""tar 兼容包装器（仅覆盖 p4a 所需子集）

背景：Docker Desktop Rosetta 模拟 x86_64 时，GNU tar 触发未实现的系统调用
（openat2 等）导致 "Cannot open: Function not implemented"。
Python tarfile 走经典 open() 调用，在 Rosetta 下正常。

支持：
  tar xf FILE [-C DIR] [--strip-components=N]   解压（gzip/bzip2/xz 自动识别）
  tar tf FILE                                   列出成员
其余选项（-v/-z/-j/-J/--no-same-owner 等）忽略。
"""
import os
import sys
import tarfile


def parse_args(argv):
    mode = None          # 'x' or 't'
    file_path = None
    directory = "."
    strip = 0
    positional = []

    option_letters = set("xtcfCzjJvhpook")

    def apply_cluster(cluster, next_args):
        """处理短选项簇，如 xf / xzf / tf；f/C 可吃掉下一个参数。
        返回消耗掉的后续参数个数。"""
        nonlocal mode, file_path, directory
        consumed = 0
        j = 0
        while j < len(cluster):
            ch = cluster[j]
            if ch in ("x", "t", "c"):
                mode = ch
            elif ch == "f":
                rest = cluster[j + 1:]
                if rest:
                    file_path = rest
                else:
                    file_path = next_args[consumed]
                    consumed += 1
                return consumed  # f 之后的字符必为文件名
            elif ch == "C":
                rest = cluster[j + 1:]
                if rest:
                    directory = rest
                else:
                    directory = next_args[consumed]
                    consumed += 1
                return consumed
            # z/j/J/v/p/o/h/k 等忽略
            j += 1
        return consumed

    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            if a.startswith("--strip-components="):
                strip = int(a.split("=", 1)[1])
            elif a == "--strip-components":
                i += 1
                strip = int(argv[i])
            elif a.startswith("--directory="):
                directory = a.split("=", 1)[1]
            elif a == "--directory":
                i += 1
                directory = argv[i]
            elif a.startswith("--file="):
                file_path = a.split("=", 1)[1]
            # 其它长选项（--no-same-owner 等）一律忽略
            i += 1
            continue

        if a.startswith("-") and a != "-":
            i += 1 + apply_cluster(a.lstrip("-"), argv[i + 1:])
            continue

        # 老式无横杠短选项簇（tar xf FILE / tar tf FILE）
        if len(a) <= 4 and all(c in option_letters for c in a):
            i += 1 + apply_cluster(a, argv[i + 1:])
            continue

        # 位置参数：第一个通常是压缩包
        positional.append(a)
        i += 1

    if file_path is None and positional:
        file_path = positional[0]
    return mode, file_path, directory, strip


def strip_name(name, n):
    if not n:
        return name
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if len(parts) <= n:
        return None
    return "/".join(parts[n:])


def main(argv):
    mode, file_path, directory, strip = parse_args(argv)
    if not file_path:
        sys.stderr.write("tar wrapper: 缺少文件名\n")
        return 2

    with tarfile.open(file_path, "r:*") as tf:
        if mode == "t":
            for m in tf.getmembers():
                sys.stdout.write(m.name + "\n")
            return 0

        os.makedirs(directory, exist_ok=True)
        base = os.path.abspath(directory)
        for m in tf.getmembers():
            new_name = strip_name(m.name, strip)
            if not new_name:
                continue
            # 防路径穿越
            target = os.path.abspath(os.path.join(base, new_name))
            if not (target == base or target.startswith(base + os.sep)):
                continue
            m.name = new_name
            if m.linkname:
                ln = strip_name(m.linkname, strip)
                m.linkname = ln or m.linkname
            try:
                tf.extract(m, base, filter="fully_trusted", set_attrs=True)
            except TypeError:
                # 旧版 Python 无 filter 参数
                tf.extract(m, base)
            except FileExistsError:
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
