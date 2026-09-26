import type { SVGProps } from 'react';

/* Inline, stroked, 16px, currentColor. No icon package.
 *
 * currentColor is the point: the rail sets colour from a token and the icon
 * inherits it, so there is no second place where the accent is decided. An icon
 * font or an SVG sprite with baked-in fills would be exactly that second place,
 * and it is the one nobody remembers to retheme.
 */

type IconProps = SVGProps<SVGSVGElement>;

function Svg({ children, ...rest }: IconProps) {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.25"
      strokeLinecap="square"
      strokeLinejoin="miter"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {children}
    </svg>
  );
}

export const IconTerminal = (p: IconProps) => (
  <Svg {...p}>
    <rect x="1.5" y="2.5" width="13" height="11" />
    <path d="M4 6l2.5 2L4 10M8.5 10.5H12" />
  </Svg>
);

export const IconStatus = (p: IconProps) => (
  <Svg {...p}>
    <path d="M1.5 8.5h3l2-5 2.5 10 2-5h3.5" />
  </Svg>
);

export const IconBoard = (p: IconProps) => (
  <Svg {...p}>
    <rect x="1.5" y="2.5" width="4" height="11" />
    <rect x="6.5" y="2.5" width="4" height="7" />
    <rect x="11.5" y="2.5" width="3" height="9" />
  </Svg>
);

export const IconRuns = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="8" cy="8" r="6" />
    <path d="M8 4.5V8l2.5 1.5" />
  </Svg>
);

export const IconOrg = (p: IconProps) => (
  <Svg {...p}>
    <rect x="6" y="1.5" width="4" height="3.5" />
    <rect x="1.5" y="11" width="4" height="3.5" />
    <rect x="10.5" y="11" width="4" height="3.5" />
    <path d="M8 5v3.5M3.5 11V8.5h9V11" />
  </Svg>
);

export const IconField = (p: IconProps) => (
  <Svg {...p}>
    <rect x="1.5" y="5.5" width="13" height="5" />
    <path d="M4 5.5v-3M12 5.5v-3M4 13.5v-3M12 13.5v-3M5 8h6" />
  </Svg>
);

export const IconGit = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="4" cy="3.5" r="2" />
    <circle cx="4" cy="12.5" r="2" />
    <circle cx="12" cy="6.5" r="2" />
    <path d="M4 5.5v5M12 8.5c0 2-3 1.5-4.5 2.5" />
  </Svg>
);

export const IconSettings = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="8" cy="8" r="2.25" />
    <path d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M12.6 3.4l-1.4 1.4M4.8 11.2l-1.4 1.4" />
  </Svg>
);

export const IconPin = (p: IconProps) => (
  <Svg {...p}>
    <rect x="1.5" y="2.5" width="13" height="11" />
    <path d="M10 2.5v11" />
  </Svg>
);

export const IconFloat = (p: IconProps) => (
  <Svg {...p}>
    <rect x="1.5" y="2.5" width="13" height="11" />
    <rect x="8" y="5" width="5.5" height="8.5" />
  </Svg>
);

export const IconClose = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3.5 3.5l9 9M12.5 3.5l-9 9" />
  </Svg>
);

export const IconChevron = (p: IconProps) => (
  <Svg {...p}>
    <path d="M6 4l4 4-4 4" />
  </Svg>
);
