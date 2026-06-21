/**
 * AudioRecorder — captures microphone at 16 kHz, calls onChunk with base64 PCM16 data.
 * AudioStreamer — receives base64 PCM16 at 24 kHz from the server and plays it.
 */

const TARGET_SAMPLE_RATE = 16000;

function floatTo16BitPCM(float32: Float32Array): Int16Array {
  const result = new Int16Array(float32.length);
  for (let i = 0; i < float32.length; i++) {
    const clamped = Math.max(-1, Math.min(1, float32[i]));
    result[i] = clamped * 0x7fff;
  }
  return result;
}

// Average-based downsampling from fromRate → TARGET_SAMPLE_RATE
function downsample(buffer: Float32Array, fromRate: number): Float32Array {
  if (fromRate === TARGET_SAMPLE_RATE) return buffer;
  const ratio = fromRate / TARGET_SAMPLE_RATE;
  const newLength = Math.round(buffer.length / ratio);
  const result = new Float32Array(newLength);
  for (let i = 0; i < newLength; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(Math.floor((i + 1) * ratio), buffer.length);
    let sum = 0;
    for (let j = start; j < end; j++) sum += buffer[j];
    result[i] = sum / (end - start);
  }
  return result;
}

export class AudioRecorder {
  private ctx: AudioContext | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private workletNode: AudioWorkletNode | null = null;
  private stream: MediaStream | null = null;

  constructor(private onChunk: (base64: string) => void) {}

  async start(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });

    this.ctx = new AudioContext();
    const nativeRate = this.ctx.sampleRate;

    await this.ctx.audioWorklet.addModule('/audio-processor.js');

    this.source = this.ctx.createMediaStreamSource(this.stream);
    this.workletNode = new AudioWorkletNode(this.ctx, 'audio-capture-processor');

    this.workletNode.port.onmessage = (e: MessageEvent<Float32Array>) => {
      const resampled = downsample(e.data, nativeRate);
      const pcm = floatTo16BitPCM(resampled);
      const bytes = new Uint8Array(pcm.buffer);
      // P6: spread into String.fromCharCode avoids per-element string concat
      const CHUNK = 2048;
      let binary = '';
      for (let i = 0; i < bytes.length; i += CHUNK) {
        binary += String.fromCharCode(...bytes.subarray(i, i + CHUNK));
      }
      this.onChunk(btoa(binary));
    };

    this.source.connect(this.workletNode);
    // AudioWorkletNode must be connected to destination to keep the graph alive
    this.workletNode.connect(this.ctx.destination);
  }

  stop(): void {
    this.workletNode?.disconnect();
    this.source?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop());
    this.ctx?.close();
    this.ctx = null;
  }
}

export class AudioStreamer {
  private ctx: AudioContext;
  private nextStartTime: number;

  constructor() {
    this.ctx = new AudioContext({ sampleRate: 24000 });
    this.nextStartTime = this.ctx.currentTime;
  }

  playChunk(base64: string): void {
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);

    const int16 = new Int16Array(bytes.buffer);
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 32768;

    const buffer = this.ctx.createBuffer(1, float32.length, 24000);
    buffer.copyToChannel(float32, 0);

    const source = this.ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(this.ctx.destination);

    const now = this.ctx.currentTime;
    if (this.nextStartTime < now) this.nextStartTime = now;
    source.start(this.nextStartTime);
    this.nextStartTime += buffer.duration;
  }

  stop(): void {
    this.ctx.close();
    this.nextStartTime = 0;
  }
}
