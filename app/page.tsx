import type { Metadata } from "next";
import { OhIcApp } from "./OhIcApp";

export const metadata: Metadata = {
  title: "OhIc — AI video enhancement",
  description: "Restore and upscale videos with Real-ESRGAN.",
};

export default function Home() {
  return <OhIcApp />;
}
