/**
 * TalkSync AI — HTML5 Canvas Dynamic Glowing Audio Waveform Visualizer
 */
(function () {
    "use strict";

    class WaveformVisualizer {
        constructor(canvasId) {
            this.canvas = document.getElementById(canvasId) || document.getElementById("waveformCanvas") || document.getElementById("waveform-canvas");
            if (!this.canvas) return;
            this.ctx = this.canvas.getContext("2d");
            this.bufferSize = 64;
            this.buffer = new Array(this.bufferSize).fill(0);
            this.targetLevel = 0;
            this.currentLevel = 0;
            this.phase = 0;

            this.resize();
            window.addEventListener("resize", () => this.resize());
            this.loop();
        }

        resize() {
            if (!this.canvas) return;
            const rect = this.canvas.getBoundingClientRect();
            this.dpr = window.devicePixelRatio || 1;
            this.width = rect.width || 400;
            this.height = rect.height || 60;
            this.canvas.width = this.width * this.dpr;
            this.canvas.height = this.height * this.dpr;
            this.ctx.scale(this.dpr, this.dpr);
        }

        draw(level, rms) {
            const raw = Math.max(Number(level) || 0, Number(rms) || 0);
            // Non-linear perceptual scaling: boosts normal 0.005-0.05 speech RMS into a rich 0.15 - 0.95 visual range
            let scaled = 0;
            if (raw > 0.0002) {
                scaled = Math.min(1.0, Math.pow(raw, 0.45) * 2.8);
            }
            this.targetLevel = Math.max(this.targetLevel, scaled);
        }

        loop() {
            // Smooth attack and release
            this.currentLevel += (this.targetLevel - this.currentLevel) * 0.35;
            this.targetLevel *= 0.85; // Decay
            this.phase += 0.08 + (this.currentLevel * 0.15);

            // Shift sliding amplitude history
            this.buffer.shift();
            this.buffer.push(this.currentLevel);

            this.render();
            requestAnimationFrame(() => this.loop());
        }

        render() {
            const { ctx, width, height, buffer, currentLevel, phase } = this;
            if (!ctx || !width || !height) return;

            ctx.clearRect(0, 0, width, height);

            const centerY = height / 2;
            const step = width / (buffer.length - 1);
            const idleAmp = 0.04 * (height * 0.2); // Subtle idle wave
            const amp = (currentLevel * (height * 0.42)) + idleAmp;

            // --- Layer 1: Background Soft Glow Wave Area ---
            ctx.beginPath();
            ctx.moveTo(0, centerY);
            for (let i = 0; i < buffer.length; i++) {
                const x = i * step;
                const wave = Math.sin((i * 0.25) + phase) * (buffer[i] * height * 0.35 + idleAmp);
                ctx.lineTo(x, centerY - wave);
            }
            ctx.lineTo(width, centerY);
            for (let i = buffer.length - 1; i >= 0; i--) {
                const x = i * step;
                const wave = Math.sin((i * 0.25) + phase) * (buffer[i] * height * 0.35 + idleAmp);
                ctx.lineTo(x, centerY + wave);
            }
            ctx.closePath();

            const fillGrad = ctx.createLinearGradient(0, 0, width, 0);
            fillGrad.addColorStop(0, "rgba(56, 189, 248, 0.12)");
            fillGrad.addColorStop(0.5, "rgba(99, 102, 241, 0.20)");
            fillGrad.addColorStop(1, "rgba(168, 85, 247, 0.12)");
            ctx.fillStyle = fillGrad;
            ctx.fill();

            // --- Layer 2: Main Foreground Crisp Glowing Wave ---
            ctx.beginPath();
            ctx.moveTo(0, centerY);

            for (let i = 0; i < buffer.length - 1; i++) {
                const x1 = i * step;
                const y1 = centerY - Math.sin((i * 0.3) + phase) * (buffer[i] * height * 0.4 + idleAmp);
                const x2 = (i + 1) * step;
                const y2 = centerY - Math.sin(((i + 1) * 0.3) + phase) * (buffer[i + 1] * height * 0.4 + idleAmp);
                const xc = (x1 + x2) / 2;
                const yc = (y1 + y2) / 2;
                ctx.quadraticCurveTo(x1, y1, xc, yc);
            }

            const strokeGrad = ctx.createLinearGradient(0, 0, width, 0);
            strokeGrad.addColorStop(0, "#38bdf8");
            strokeGrad.addColorStop(0.5, "#818cf8");
            strokeGrad.addColorStop(1, "#c084fc");

            ctx.strokeStyle = strokeGrad;
            ctx.lineWidth = 2.5;
            ctx.shadowColor = currentLevel > 0.05 ? "#38bdf8" : "transparent";
            ctx.shadowBlur = currentLevel > 0.05 ? 10 : 0;
            ctx.stroke();
            ctx.shadowBlur = 0;
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", () => {
            window.WaveformVisualizer = new WaveformVisualizer("waveformCanvas");
        });
    } else {
        window.WaveformVisualizer = new WaveformVisualizer("waveformCanvas");
    }
})();
