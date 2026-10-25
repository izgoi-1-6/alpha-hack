import { crc32, deflateSync } from "node:zlib";
import { Page } from "@playwright/test";

// Synthetic upload files built by the tests themselves: nothing is a real document and nothing holds personal data.
// PDFs and PNGs are written byte by byte (hand-computed cross-reference offsets, zlib and CRC chunks), JPEGs come from
// the browser's own canvas encoder. Each is the smallest structurally valid file the demo document check accepts.

export type UploadFile = { name: string; mimeType: string; buffer: Buffer };

/** A one-page PDF 1.4 with a correct cross-reference table; `padding` spaces in the content stream grow it. */
export function pdfBytes({
  text = "Synthetic demo document",
  padding = 0,
}: { text?: string; padding?: number } = {}) {
  const content = `BT /F1 12 Tf 20 100 Td (${text}) Tj ET\n` + " ".repeat(padding);
  const bodies = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R /Resources << >> >>",
    `<< /Length ${content.length} >>\nstream\n${content}\nendstream`,
  ];
  let out = "%PDF-1.4\n";
  const offsets: number[] = [];
  bodies.forEach((body, index) => {
    offsets.push(out.length);
    out += `${index + 1} 0 obj\n${body}\nendobj\n`;
  });
  const xref = out.length;
  out += `xref\n0 ${bodies.length + 1}\n0000000000 65535 f \n`;
  out += offsets.map((offset) => `${String(offset).padStart(10, "0")} 00000 n \n`).join("");
  out += `trailer\n<< /Size ${bodies.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(out, "latin1");
}

function pngChunk(kind: string, data: Buffer) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(kind, "latin1"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body) >>> 0);
  return Buffer.concat([length, body, crc]);
}

/** An RGB PNG of a few red pixels. */
export function pngBytes(width = 4, height = 3) {
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header.set([8, 2, 0, 0, 0], 8);
  const row = Buffer.concat([Buffer.from([0]), Buffer.from("c81414".repeat(width), "hex")]);
  const rows = Buffer.concat(Array.from({ length: height }, () => row));
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    pngChunk("IHDR", header),
    pngChunk("IDAT", deflateSync(rows)),
    pngChunk("IEND", Buffer.alloc(0)),
  ]);
}

/** A small JPEG drawn on a canvas in the page and encoded by the browser. */
export async function jpegBytes(page: Page) {
  const dataUrl = await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    canvas.width = 16;
    canvas.height = 16;
    const context = canvas.getContext("2d")!;
    context.fillStyle = "#c81414";
    context.fillRect(0, 0, 16, 16);
    return canvas.toDataURL("image/jpeg", 0.9);
  });
  return Buffer.from(dataUrl.split(",")[1], "base64");
}

export const pdfFile = (name: string, options?: Parameters<typeof pdfBytes>[0]): UploadFile => ({
  name,
  mimeType: "application/pdf",
  buffer: pdfBytes(options),
});
export const pngFile = (name: string): UploadFile => ({
  name,
  mimeType: "image/png",
  buffer: pngBytes(),
});
export const jpegFile = async (page: Page, name: string): Promise<UploadFile> => ({
  name,
  mimeType: "image/jpeg",
  buffer: await jpegBytes(page),
});
/** An HTML page renamed to .pdf: the browser sends it as a PDF, the server's content check refuses it. */
export const htmlAsPdf = (name: string): UploadFile => ({
  name,
  mimeType: "application/pdf",
  buffer: Buffer.from(
    "<!DOCTYPE html><html><body><script>alert(1)</script></body></html>",
    "latin1",
  ),
});
