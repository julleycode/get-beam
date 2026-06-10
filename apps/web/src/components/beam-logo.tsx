/**
 * Beam logo mark (gradient beam + sparkles). Extracted from the dashboard
 * sidebar so the auth splash can reuse the identical mark.
 */
export function BeamLogo({ className = "w-7" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 100 64"
      className={`inline-block shrink-0 ${className}`}
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="beamLogoGrad" x1="0" y1="0" x2="1" y2="0.35">
          <stop offset="0" stopColor="#FF6B9D" />
          <stop offset="0.55" stopColor="#FF3366" />
          <stop offset="1" stopColor="#FF7FA8" />
        </linearGradient>
      </defs>
      <path
        d="M26,15 Q26,32 90,32 Q26,32 26,49 Q26,32 9,32 Q26,32 26,15 Z"
        fill="url(#beamLogoGrad)"
      />
      <circle cx="26" cy="32" r="3.4" fill="#fff" opacity="0.92" />
      <path
        d="M82,21 Q84,25 88,25 Q84,25 82,29 Q80,25 76,25 Q80,25 82,21 Z"
        fill="url(#beamLogoGrad)"
        opacity="0.85"
      />
      <circle cx="89" cy="40" r="2.1" fill="url(#beamLogoGrad)" opacity="0.7" />
    </svg>
  );
}
