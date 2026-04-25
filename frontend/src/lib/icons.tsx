type IconProps = {
  className?: string;
  strokeWidth?: number;
};

const base = (className = "h-5 w-5") =>
  `${className} stroke-current`;

export function MountainIcon({ className, strokeWidth = 1.6 }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={base(className)}
      fill="none"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M3 19l5-9 4 6 3-4 6 7H3z" />
      <path d="M8 10l1.6-2.8" opacity="0.6" />
    </svg>
  );
}

export function SnowflakeIcon({ className, strokeWidth = 1.6 }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={base(className)}
      fill="none"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M12 2v20M4.2 6.5l15.6 11M4.2 17.5l15.6-11" />
      <path d="M9 4l3 2 3-2M9 20l3-2 3 2M2 9l2 3-2 3M22 9l-2 3 2 3" />
    </svg>
  );
}

export function TrendIcon({ className, strokeWidth = 1.6 }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={base(className)}
      fill="none"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M3 17l5-5 4 3 8-9" />
      <path d="M16 6h4v4" />
    </svg>
  );
}

export function StatsIcon({ className, strokeWidth = 1.6 }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={base(className)}
      fill="none"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="12" cy="12" r="9" />
      <path d="M12 3v9l7 4" />
    </svg>
  );
}

export function WaterDropIcon({ className, strokeWidth = 1.6 }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={base(className)}
      fill="none"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M12 2.5c-3 4.5-6 7.8-6 11.5a6 6 0 0 0 12 0c0-3.7-3-7-6-11.5z" />
      <path d="M9 14a3 3 0 0 0 3 3" opacity="0.5" />
    </svg>
  );
}

export function HikerIcon({ className, strokeWidth = 1.6 }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={base(className)}
      fill="none"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="14" cy="4.5" r="1.5" />
      <path d="M9 21l3-7-3-3 4-4 4 4 3 1" />
      <path d="M5 12l3-2 3 4" />
    </svg>
  );
}

export function ChevronLeftIcon({ className, strokeWidth = 1.8 }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={base(className)}
      fill="none"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M15 6l-6 6 6 6" />
    </svg>
  );
}

export function ChevronRightIcon({ className, strokeWidth = 1.8 }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={base(className)}
      fill="none"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M9 6l6 6-6 6" />
    </svg>
  );
}

export function CloseIcon({ className, strokeWidth = 1.8 }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={base(className)}
      fill="none"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  );
}

export function LogoMark({ className }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={base(className)}
      fill="none"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M12 2v20M4.2 6.5l15.6 11M4.2 17.5l15.6-11" />
      <circle cx="12" cy="12" r="2.4" fill="currentColor" stroke="none" />
    </svg>
  );
}
