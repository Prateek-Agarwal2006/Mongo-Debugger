export function StitchIcon({
  name,
  className = "",
  filled = false,
  size = 24,
}: Readonly<{
  name: string;
  className?: string;
  filled?: boolean;
  size?: number;
}>) {
  return (
    <span
      className={`material-symbols-outlined ${className}`}
      style={{
        fontSize: size,
        fontVariationSettings: filled ? "'FILL' 1" : "'FILL' 0",
      }}
      aria-hidden="true"
    >
      {name}
    </span>
  );
}
