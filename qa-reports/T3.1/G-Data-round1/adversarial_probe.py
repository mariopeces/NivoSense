import sys, email.utils, datetime as dt
sys.path.insert(0, sys.argv[1])
from ingest_webcams import probe_camera_image, ImageResponse
img = sys.argv[2]
now = email.utils.format_datetime(dt.datetime.now(dt.timezone.utc), usegmt=True)
def resp(path, lm):
    b = open(path, 'rb').read()
    return ImageResponse(200, 'image/jpeg', len(b), b, lm)
cases = {
 'A unfingerprinted feratel placeholder rendition (real size-38 bytes), fresh LM': (f'{img}/ph38.jpg', f'{img}/ph38.jpg', now),
 'B real 15111/0 frame burned 18:08 CET, served with fresh LM (frozen cam)': (f'{img}/15111_0_37.jpg', f'{img}/15111_0_35.jpg', now),
 'C real placeholder size37 + size35 (control)': (f'{img}/15110_2_37.jpg', f'{img}/15110_2_35.jpg', now),
 'D thumb = 18:08 frame, large = placeholder size38': (f'{img}/15111_0_37.jpg', f'{img}/ph38.jpg', now),
}
for name, (t, l, lm) in cases.items():
    cam = {'id': 'x', 'thumbnail_url': 'https://t', 'large_url': 'https://l'}
    m = {'https://t': t, 'https://l': l}
    r = probe_camera_image(cam, lambda u: resp(m[u], lm))
    print(name, '->', cam['status'], cam['captured_at'], r['problem'])
