const CSS_VARS = `:root{--blue:#1a4b8c;--red:#c0392b;--green:#27ae60;--amber:#d68910;
  --gray:#555;--light:#f5f7fa;--border:#dde3ec;--card:#fff;
  --shadow:0 2px 8px rgba(0,0,0,.08);}`;

export async function captureElement(el: HTMLElement, filename: string): Promise<void> {
  const { default: html2canvas } = await import('html2canvas');
  const canvas = await html2canvas(el, {
    scale: 2,
    useCORS: true,
    backgroundColor: '#ffffff',
    logging: false,
    onclone: (doc: Document) => {
      const s = doc.createElement('style');
      s.textContent = CSS_VARS;
      doc.head.appendChild(s);
    },
  });
  triggerDownload(canvas.toDataURL('image/png'), `${filename}.png`);
}

export function downloadCanvas(canvas: HTMLCanvasElement, filename: string): void {
  triggerDownload(canvas.toDataURL('image/png'), `${filename}.png`);
}

function triggerDownload(dataUrl: string, filename: string): void {
  const a = document.createElement('a');
  a.download = filename;
  a.href = dataUrl;
  a.click();
}
