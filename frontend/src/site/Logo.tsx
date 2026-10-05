/** Support IQ logo: a speech bubble with signal bars. */
export function Logo({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="8" fill="#4A1F0F" />
      <path d="M8 9.5h16a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-9l-4.5 3.5V21.5H8a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2Z" fill="#F5C518" />
      <rect x="11" y="16" width="2.2" height="3" rx="1" fill="#4A1F0F" />
      <rect x="14.9" y="14" width="2.2" height="5" rx="1" fill="#4A1F0F" />
      <rect x="18.8" y="12" width="2.2" height="7" rx="1" fill="#4A1F0F" />
    </svg>
  );
}

export function Wordmark() {
  return (
    <span className="s-wordmark">
      <Logo />
      <span>Support <b>IQ</b></span>
    </span>
  );
}
