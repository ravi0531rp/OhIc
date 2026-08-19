import type { Metadata } from "next";
import { OhIcApp } from "./OhIcApp";

export const metadata: Metadata = {
  title: "OhIc — Local AI video restoration",
  description: "Bring old videos back into focus with private, local AI enhancement.",
};

export default function Home() {
  return <OhIcApp />;
}
