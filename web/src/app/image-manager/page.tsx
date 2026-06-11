"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function ImageManagerPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/accounts");
  }, [router]);

  return null;
}
