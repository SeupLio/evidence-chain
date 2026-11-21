type P = { size?: number; className?: string; strokeWidth?: number };

const base = (size = 16, sw = 1.6) => ({
  width: size,
  height: size,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: sw,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
});

export const Mark = ({ size = 19 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
    <path d="M12 2.4 21 7.4v9.2L12 21.6 3 16.6V7.4z" stroke="currentColor" strokeWidth="1.5" />
    <path d="M8.2 12.3l2.6 2.6 5-5.4" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export const ArrowUpRight = ({ size = 16, className, strokeWidth = 1.8 }: P) => (
  <svg {...base(size, strokeWidth)} className={className}>
    <path d="M7 17 17 7M9 7h8v8" />
  </svg>
);

export const ArrowDown = ({ size = 14, className, strokeWidth = 1.8 }: P) => (
  <svg {...base(size, strokeWidth)} className={className}>
    <path d="M12 5v14M6 13l6 6 6-6" />
  </svg>
);

export const Check = ({ size = 13, className, strokeWidth = 2 }: P) => (
  <svg {...base(size, strokeWidth)} className={className}>
    <path d="M4.5 12.5l5 5 10-11" />
  </svg>
);

export const Play = ({ size = 15, className }: P) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={className}>
    <path d="M8 5.4v13.2c0 .8.9 1.3 1.6.9l10-6.6c.6-.4.6-1.3 0-1.7l-10-6.6c-.7-.4-1.6.1-1.6.8z" />
  </svg>
);

export const File = ({ size = 14, className, strokeWidth = 1.5 }: P) => (
  <svg {...base(size, strokeWidth)} className={className}>
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
    <path d="M14 3v5h5M9 13h6M9 17h4" />
  </svg>
);

export const Layers = ({ size = 14, className, strokeWidth = 1.5 }: P) => (
  <svg {...base(size, strokeWidth)} className={className}>
    <path d="M12 3 3 7.5l9 4.5 9-4.5z" />
    <path d="M3 12.5 12 17l9-4.5M3 17 12 21.5 21 17" />
  </svg>
);

export const Shield = ({ size = 14, className, strokeWidth = 1.5 }: P) => (
  <svg {...base(size, strokeWidth)} className={className}>
    <path d="M12 3 5 6v6c0 4.2 2.9 7.6 7 9 4.1-1.4 7-4.8 7-9V6z" />
    <path d="M9 12l2 2 4-4.2" />
  </svg>
);

export const Spark = ({ size = 14, className }: P) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={className}>
    <path d="M12 2.5c.5 4.6 3 7.2 7.5 7.7-4.5.5-7 3.1-7.5 7.7-.5-4.6-3-7.2-7.5-7.7 4.5-.5 7-3.1 7.5-7.7z" />
  </svg>
);

export const Network = ({ size = 14, className, strokeWidth = 1.5 }: P) => (
  <svg {...base(size, strokeWidth)} className={className}>
    <circle cx="12" cy="5" r="2.2" />
    <circle cx="5" cy="18" r="2.2" />
    <circle cx="19" cy="18" r="2.2" />
    <path d="M12 7.2v4.4M12 11.6 6.6 16M12 11.6 17.4 16" />
  </svg>
);

export const Close = ({ size = 14, className, strokeWidth = 1.8 }: P) => (
  <svg {...base(size, strokeWidth)} className={className}>
    <path d="M6 6l12 12M18 6 6 18" />
  </svg>
);

export const Search = ({ size = 14, className, strokeWidth = 1.8 }: P) => (
  <svg {...base(size, strokeWidth)} className={className}>
    <circle cx="11" cy="11" r="6.5" />
    <path d="M16 16l4.5 4.5" />
  </svg>
);

export const Command = ({ size = 12, className, strokeWidth = 1.6 }: P) => (
  <svg {...base(size, strokeWidth)} className={className}>
    <path d="M9 6a3 3 0 1 0-3 3h12a3 3 0 1 0-3-3v12a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3z" />
  </svg>
);

export const Download = ({ size = 14, className, strokeWidth = 1.6 }: P) => (
  <svg {...base(size, strokeWidth)} className={className}>
    <path d="M12 3v12M7 10l5 5 5-5M4 20h16" />
  </svg>
);

export const Pin = ({ size = 13, className, strokeWidth = 1.6 }: P) => (
  <svg {...base(size, strokeWidth)} className={className}>
    <path d="M9 3h6l-1 7 4 3v2H6v-2l4-3z" />
    <path d="M12 15v6" />
  </svg>
);

export const Moon = ({ size = 14, className, strokeWidth = 1.6 }: P) => (
  <svg {...base(size, strokeWidth)} className={className}>
    <path d="M20 14.5A8 8 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z" />
  </svg>
);

export const Sun = ({ size = 14, className, strokeWidth = 1.6 }: P) => (
  <svg {...base(size, strokeWidth)} className={className}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.2 5.2l1.4 1.4M17.4 17.4l1.4 1.4M18.8 5.2l-1.4 1.4M6.6 17.4l-1.4 1.4" />
  </svg>
);


