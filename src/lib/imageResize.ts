/**
 * 写真取り込み時のリサイズ・JPEG圧縮(iOS Safariの容量対策)。
 * 本画像: 長辺1500px quality 0.82 / サムネイル: 長辺300px
 */

const MAIN_MAX = 1500;
const MAIN_QUALITY = 0.82;
const THUMB_MAX = 300;
const THUMB_QUALITY = 0.75;

async function decodeImage(file: Blob): Promise<ImageBitmap | HTMLImageElement> {
  // createImageBitmapはEXIF回転を自動適用する(iOS 17+/モダンブラウザ)
  if ('createImageBitmap' in window) {
    try {
      return await createImageBitmap(file);
    } catch {
      // HEICなどデコード不可の場合は<img>にフォールバック
    }
  }
  return new Promise((resolve, reject) => {
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve(img);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('image decode failed'));
    };
    img.src = url;
  });
}

function drawToJpeg(
  source: ImageBitmap | HTMLImageElement,
  maxEdge: number,
  quality: number,
): Promise<Blob> {
  const srcW = source.width;
  const srcH = source.height;
  const scale = Math.min(1, maxEdge / Math.max(srcW, srcH));
  const w = Math.round(srcW * scale);
  const h = Math.round(srcH * scale);

  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('canvas 2d context unavailable');
  // 白背景(透過PNG→JPEG時の黒つぶれ防止)
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, w, h);
  ctx.drawImage(source, 0, 0, w, h);

  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error('toBlob failed'))),
      'image/jpeg',
      quality,
    );
  });
}

export interface ResizedImage {
  imageBlob: Blob; // 長辺1500px
  thumbBlob: Blob; // 長辺300px
}

/** 写真1枚を本画像+サムネイルに変換する */
export async function resizeImage(file: Blob): Promise<ResizedImage> {
  const source = await decodeImage(file);
  try {
    const imageBlob = await drawToJpeg(source, MAIN_MAX, MAIN_QUALITY);
    const thumbBlob = await drawToJpeg(source, THUMB_MAX, THUMB_QUALITY);
    return { imageBlob, thumbBlob };
  } finally {
    if ('close' in source) source.close();
  }
}
