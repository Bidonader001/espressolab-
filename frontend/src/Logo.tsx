export function Logo({ size = "md" }: { size?: "md" | "lg" }) {
  return <img className={`logo ${size}`} src="/logo.png" alt="EspressoLab" />;
}
