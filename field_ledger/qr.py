"""QR codes, so a phone can join the hub by pointing its camera at the laptop. Pure.

The standard library has none, and the only thing we encode is the hub's setup address, so
this is the smallest correct subset of ISO/IEC 18004: byte mode, error correction level M,
versions 1 to 6 (up to 106 bytes). The layout follows the spec step by step; the mask is
chosen by the spec's penalty rules so the code scans well off a laptop screen.
"""

# ponytail: versions 1-6 only (no version-info bits needed); 7+ if a setup URL ever outgrows 106 bytes
# version -> (data codewords per block, number of blocks, EC codewords per block, alignment centres)
LEVEL_M = {
    1: (16, 1, 10, []),
    2: (28, 1, 16, [6, 18]),
    3: (44, 1, 26, [6, 22]),
    4: (32, 2, 18, [6, 26]),
    5: (43, 2, 24, [6, 30]),
    6: (27, 4, 16, [6, 34]),
}


def gf_mul(x: int, y: int) -> int:
    """Multiply in GF(2^8) modulo x^8 + x^4 + x^3 + x^2 + 1, the field QR codes use."""
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def rs_divisor(degree: int) -> list[int]:
    """Reed-Solomon generator polynomial (x - 2^0)(x - 2^1)... without its leading 1."""
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = gf_mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = gf_mul(root, 0x02)
    return result


def rs_remainder(data: list[int], divisor: list[int]) -> list[int]:
    result = [0] * len(divisor)
    for byte in data:
        factor = byte ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= gf_mul(coef, factor)
    return result


def version_for(length: int) -> int:
    for version, (per_block, blocks, _, _) in LEVEL_M.items():
        if (per_block * blocks * 8 - 12) // 8 >= length:      # 4-bit mode + 8-bit count
            return version
    raise ValueError(f"{length} bytes is too long for a QR code here (106 at most).")


def codewords(data: bytes, version: int) -> list[int]:
    """Mode, count, data, terminator and padding; split into blocks; each block's error
    correction appended; then interleaved, as the spec lays them out."""
    per_block, blocks, ec, _ = LEVEL_M[version]
    bits = "0100" + f"{len(data):08b}" + "".join(f"{b:08b}" for b in data)
    capacity = per_block * blocks * 8
    bits += "0" * min(4, capacity - len(bits))
    bits += "0" * (-len(bits) % 8)
    stream = [int(bits[i:i + 8], 2) for i in range(0, len(bits), 8)]
    stream += [0xEC, 0x11] * ((capacity // 8 - len(stream)) // 2 + 1)
    stream = stream[:capacity // 8]
    divisor = rs_divisor(ec)
    split = [stream[i * per_block:(i + 1) * per_block] for i in range(blocks)]
    checks = [rs_remainder(block, divisor) for block in split]
    return ([block[i] for i in range(per_block) for block in split]
            + [check[i] for i in range(ec) for check in checks])


MASKS = [
    lambda x, y: (x + y) % 2 == 0,
    lambda x, y: y % 2 == 0,
    lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0,
    lambda x, y: (x // 3 + y // 2) % 2 == 0,
    lambda x, y: x * y % 2 + x * y % 3 == 0,
    lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
]


class Grid:
    """The module matrix, plus which modules are fixed patterns (never data, never masked)."""

    def __init__(self, version: int):
        self.size = 17 + 4 * version
        self.dark = [[False] * self.size for _ in range(self.size)]
        self.fixed = [[False] * self.size for _ in range(self.size)]

    def set(self, x: int, y: int, dark: bool) -> None:
        self.dark[y][x] = dark
        self.fixed[y][x] = True


def draw_patterns(grid: Grid, version: int) -> None:
    size = grid.size
    for i in range(size):                                     # timing
        grid.set(6, i, i % 2 == 0)
        grid.set(i, 6, i % 2 == 0)
    for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):     # finders and their separators
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                x, y = cx + dx, cy + dy
                if 0 <= x < size and 0 <= y < size:
                    grid.set(x, y, max(abs(dx), abs(dy)) not in (2, 4))
    centres = LEVEL_M[version][3]
    last = len(centres) - 1
    for i, cy in enumerate(centres):                          # alignment, clear of the finders
        for j, cx in enumerate(centres):
            if (i, j) in ((0, 0), (0, last), (last, 0)):
                continue
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    grid.set(cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)
    draw_format(grid, 0)                                      # reserve; real bits drawn last


def draw_format(grid: Grid, mask: int) -> None:
    """Level M (00) and the mask, BCH-protected, in both copies; plus the one dark module."""
    data = mask                                               # level M's format bits are 00
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)
    bits = (data << 10 | rem) ^ 0x5412
    bit = lambda i: (bits >> i) & 1 == 1
    size = grid.size
    for i in range(6):
        grid.set(8, i, bit(i))
    grid.set(8, 7, bit(6))
    grid.set(8, 8, bit(7))
    grid.set(7, 8, bit(8))
    for i in range(9, 15):
        grid.set(14 - i, 8, bit(i))
    for i in range(8):
        grid.set(size - 1 - i, 8, bit(i))
    for i in range(8, 15):
        grid.set(8, size - 15 + i, bit(i))
    grid.set(8, size - 8, True)


def draw_data(grid: Grid, words: list[int]) -> None:
    """Zigzag up and down two-column strips from the bottom right, skipping column 6."""
    size, i = grid.size, 0
    right = size - 1
    while right >= 1:
        if right == 6:
            right = 5
        for vert in range(size):
            for j in range(2):
                x = right - j
                upward = ((right + 1) & 2) == 0
                y = size - 1 - vert if upward else vert
                if not grid.fixed[y][x] and i < len(words) * 8:
                    grid.dark[y][x] = (words[i >> 3] >> (7 - (i & 7))) & 1 == 1
                    i += 1
        right -= 2


def apply_mask(grid: Grid, mask: int) -> None:
    rule = MASKS[mask]
    for y in range(grid.size):
        for x in range(grid.size):
            if not grid.fixed[y][x] and rule(x, y):
                grid.dark[y][x] = not grid.dark[y][x]


def penalty(dark: list[list[bool]]) -> int:
    """The spec's four rules: long runs, 2x2 blocks, finder look-alikes, dark/light balance."""
    size, score = len(dark), 0
    lines = dark + [list(col) for col in zip(*dark)]
    for line in lines:
        run = 1
        for a, b in zip(line, line[1:]):
            run = run + 1 if a == b else 1
            if run == 5:
                score += 3
            elif run > 5:
                score += 1
        text = "".join("1" if m else "0" for m in line)
        score += 40 * (text.count("10111010000") + text.count("00001011101"))
    for y in range(size - 1):
        for x in range(size - 1):
            if dark[y][x] == dark[y][x + 1] == dark[y + 1][x] == dark[y + 1][x + 1]:
                score += 3
    total = sum(map(sum, dark))
    score += 10 * (abs(total * 20 - size * size * 10) // (size * size))
    return score


def encode(text: str, mask: int | None = None) -> list[list[bool]]:
    """Rows of modules, True = dark, without the quiet zone (4 light modules) around them."""
    data = text.encode("utf-8")
    version = version_for(len(data))
    words = codewords(data, version)
    best = None
    for m in ([mask] if mask is not None else range(8)):
        grid = Grid(version)
        draw_patterns(grid, version)
        draw_data(grid, words)
        apply_mask(grid, m)
        draw_format(grid, m)
        score = penalty(grid.dark)
        if best is None or score < best[0]:
            best = (score, grid.dark)
    return best[1]


def terminal(dark: list[list[bool]]) -> str:
    """Two rows per line in half blocks, black on white with a quiet zone, so it scans
    whatever colours the terminal uses."""
    size = len(dark) + 8
    rows = [[False] * size for _ in range(4)] + \
           [[False] * 4 + row + [False] * 4 for row in dark] + \
           [[False] * size for _ in range(5)]
    chars = {(False, False): " ", (True, False): "▀", (False, True): "▄", (True, True): "█"}
    return "\n".join("\x1b[30;107m" + "".join(chars[pair] for pair in zip(top, bottom)) + "\x1b[0m"
                     for top, bottom in zip(rows[0::2], rows[1::2]))
