import { useEffect } from "react";

/** Sets the browser tab title for the current page. */
export function useTitle(title: string) {
  useEffect(() => {
    document.title = title ? `${title} · Support IQ` : "Support IQ · Help center";
  }, [title]);
}
