"""Read a classic pcap and render a labelled 1000 x 900 PNG summary."""
import argparse
from collections import Counter
import sys

if __package__:
    from .pcap import CaptureError, Reader, classify
    from .png import Canvas
else:
    from pcap import CaptureError, Reader, classify
    from png import Canvas

WIDTH, HEIGHT = 1000, 900
MAX_TALKERS = 10000


def summarize(path):
    protocols = {}
    talkers = Counter()
    first = last = None
    total = 0
    with open(path, 'rb') as stream:
        reader = Reader(stream)
        order, magic = reader.byte_order, reader.magic
        for sec, _, original, data in reader:
            protocol, source = classify(data)
            counts = protocols.setdefault(protocol, [0, 0])
            counts[0] += 1
            counts[1] += original
            if source not in talkers and len(talkers) >= MAX_TALKERS:
                raise CaptureError(f'too many source talkers: safety limit {MAX_TALKERS}')
            talkers[source] += original
            total += 1
            first = sec if first is None else min(first, sec)
            last = sec if last is None else max(last, sec)
        # A second streaming pass keeps timeline storage bounded even over years.
        span = 0 if first is None else last - first + 1
        bucket_seconds = max(1, (span + 59) // 60)
        bins = [0] * max(1, (span + bucket_seconds - 1) // bucket_seconds)
        stream.seek(0)
        for sec, _, _, _ in Reader(stream):
            bins[(sec - first) // bucket_seconds] += 1
    return dict(protocols=protocols, talkers=talkers, first=first, last=last,
                total=total, bins=bins, bucket_seconds=bucket_seconds,
                byte_order=order, magic=magic)


def bars(canvas, y, title, rows, label_width=150):
    canvas.text(32, y, title)
    left, right = 32 + label_width, 810
    maximum = max((value for _, value in rows), default=0)
    canvas.text(left, y + 20, '0', 1)
    canvas.text(right - len(str(maximum)) * 4, y + 20, maximum, 1)
    canvas.rect(left, y + 32, right - left, 1, (160, 172, 188))
    for i, (label, value) in enumerate(rows):
        yy = y + 40 + i * 17
        canvas.text(32, yy + 3, label, 1)
        canvas.rect(left, yy, 1, 14, (160, 172, 188))
        width = 0 if maximum == 0 else value * (right - left) // maximum
        canvas.rect(left + 1, yy, width, 12, (46, 123, 190))
        canvas.text(right + 12, yy + 3, value, 1)


def render(summary, output):
    c = Canvas(WIDTH, HEIGHT)
    c.text(32, 24, 'NETWORK TRAFFIC SUMMARY', 3)
    c.text(32, 52, f'{summary["total"]} PACKETS / ORIGINAL FRAME BYTES / {WIDTH} X {HEIGHT}', 1)
    c.text(32, 67, f'PCAP {summary["byte_order"]} / MAGIC {summary["magic"]}', 1)
    protocols = sorted(summary['protocols'].items())
    bars(c, 100, 'PROTOCOL / PACKETS', [(k, v[0]) for k, v in protocols])
    bars(c, 335, 'PROTOCOL / BYTES', [(k, v[1]) for k, v in protocols])
    top = sorted(summary['talkers'].items(), key=lambda item: (-item[1], item[0]))[:5]
    bars(c, 570, 'TOP 5 SOURCES / BYTES', top, label_width=330)
    c.text(32, 715, f'TIMELINE / PACKETS PER {summary["bucket_seconds"]} SECONDS')
    left, bottom, height, width = 90, 845, 90, 840
    maximum = max(summary['bins']) or 1
    c.text(32, bottom - height, maximum, 1)
    c.text(32, bottom - 5, '0', 1)
    c.rect(left, bottom - height, 1, height + 1, (80, 90, 110))
    c.rect(left, bottom, width, 1, (80, 90, 110))
    for i, value in enumerate(summary['bins']):
        x0 = left + i * width // len(summary['bins'])
        x1 = left + (i + 1) * width // len(summary['bins'])
        h = value * height // maximum
        c.rect(x0 + 1, bottom - h, max(1, x1 - x0 - 2), h, (38, 150, 129))
    c.text(left, 854, '0', 1)
    end_label = f'{len(summary["bins"]) * summary["bucket_seconds"]} SEC'
    c.text(left + width - len(end_label) * 4, 854, end_label, 1)
    c.text(250, 870, f'ELAPSED SECONDS / START UNIX {summary["first"] if summary["first"] is not None else "EMPTY"}', 1)
    if not summary['total']:
        c.text(620, 100, 'EMPTY CAPTURE')
    c.write(output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture')
    parser.add_argument('-o', '--output', required=True)
    args = parser.parse_args(argv)
    try:
        summary = summarize(args.capture)
        render(summary, args.output)
    except (CaptureError, OSError, ValueError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1
    print(f'pcap {summary["byte_order"]}, magic {summary["magic"]}; '
          f'{summary["total"]} packets; PNG {WIDTH}x{HEIGHT}: {args.output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
