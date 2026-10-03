import Link from "next/link";
import type { ReactNode } from "react";

export function ProductAction({ href, children }: { href: string; children: ReactNode }) {
  return <Link className="helloada-product-action" href={href}><span>{children}</span><i aria-hidden="true">↗</i></Link>;
}
