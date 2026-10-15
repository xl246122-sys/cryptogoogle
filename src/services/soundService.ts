/**
 * Web Audio API Synthesizer for ShotCrypto
 * Provides reliable, low-latency synthesized radar sound chimes
 * without external audio file dependencies.
 */

class SoundService {
  private ctx: AudioContext | null = null;
  private volume: number = 0.8;
  private isEnabled: boolean = true;

  private getContext(): AudioContext | null {
    if (typeof window === 'undefined') return null;
    if (!this.ctx) {
      const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      if (AudioCtx) {
        this.ctx = new AudioCtx();
      }
    }
    if (this.ctx && this.ctx.state === 'suspended') {
      this.ctx.resume().catch(() => {});
    }
    return this.ctx;
  }

  public setVolume(vol: number) {
    this.volume = Math.max(0, Math.min(1, vol));
  }

  public setEnabled(enabled: boolean) {
    this.isEnabled = enabled;
  }

  public getEnabled(): boolean {
    return this.isEnabled;
  }

  /**
   * Unlock Web Audio API on first user gesture
   */
  public unlockAudio() {
    const ctx = this.getContext();
    if (ctx && ctx.state === 'suspended') {
      ctx.resume().catch(() => {});
    }
  }

  /**
   * Play urgent Bullish Buy Opportunity chime
   * Double ascending harmonic chime with crisp penetration
   */
  public playBuySignalChime() {
    if (!this.isEnabled) return;
    const ctx = this.getContext();
    if (!ctx) return;

    try {
      const now = ctx.currentTime;
      const masterGain = ctx.createGain();
      masterGain.gain.setValueAtTime(this.volume * 0.6, now);
      masterGain.connect(ctx.destination);

      // Part 1: Ascending triad: C6 (1046.5Hz), E6 (1318.5Hz), G6 (1567.98Hz), C7 (2093Hz)
      const freqs = [1046.5, 1318.5, 1567.98, 2093.0];
      freqs.forEach((freq, index) => {
        const osc = ctx.createOscillator();
        const noteGain = ctx.createGain();

        osc.type = index === 3 ? 'sine' : 'triangle';
        osc.frequency.setValueAtTime(freq, now + index * 0.07);

        noteGain.gain.setValueAtTime(0, now + index * 0.07);
        noteGain.gain.linearRampToValueAtTime(1, now + index * 0.07 + 0.015);
        noteGain.gain.exponentialRampToValueAtTime(0.001, now + index * 0.07 + 0.38);

        osc.connect(noteGain);
        noteGain.connect(masterGain);

        osc.start(now + index * 0.07);
        osc.stop(now + index * 0.07 + 0.4);
      });

      // Part 2: Quick golden coin ping echo at +0.28s
      const echoOsc = ctx.createOscillator();
      const echoGain = ctx.createGain();
      echoOsc.type = 'sine';
      echoOsc.frequency.setValueAtTime(2637.0, now + 0.28); // E7
      echoGain.gain.setValueAtTime(0, now + 0.28);
      echoGain.gain.linearRampToValueAtTime(0.7, now + 0.29);
      echoGain.gain.exponentialRampToValueAtTime(0.001, now + 0.65);
      echoOsc.connect(echoGain);
      echoGain.connect(masterGain);
      echoOsc.start(now + 0.28);
      echoOsc.stop(now + 0.68);
    } catch {
      // Audio autoplay policy fallback
    }
  }

  /**
   * Play Risk / Stop Loss alert
   */
  public playRiskAlertChime() {
    if (!this.isEnabled) return;
    const ctx = this.getContext();
    if (!ctx) return;

    try {
      const now = ctx.currentTime;
      const masterGain = ctx.createGain();
      masterGain.gain.setValueAtTime(this.volume * 0.35, now);
      masterGain.connect(ctx.destination);

      // Warning double drop: 587Hz -> 440Hz
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sawtooth';
      osc.frequency.setValueAtTime(587.33, now);
      osc.frequency.exponentialRampToValueAtTime(440, now + 0.2);

      gain.gain.setValueAtTime(0.8, now);
      gain.gain.exponentialRampToValueAtTime(0.01, now + 0.3);

      osc.connect(gain);
      gain.connect(masterGain);

      osc.start(now);
      osc.stop(now + 0.32);
    } catch {}
  }

  /**
   * Sonar radar sweep ping for test or cycle completion
   */
  public playRadarTestPing() {
    if (!this.isEnabled) return;
    const ctx = this.getContext();
    if (!ctx) return;

    try {
      const now = ctx.currentTime;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();

      osc.type = 'sine';
      osc.frequency.setValueAtTime(880, now);
      osc.frequency.exponentialRampToValueAtTime(1760, now + 0.15);

      gain.gain.setValueAtTime(this.volume * 0.3, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.4);

      osc.connect(gain);
      gain.connect(ctx.destination);

      osc.start(now);
      osc.stop(now + 0.42);
    } catch {}
  }
}

export const soundService = new SoundService();
