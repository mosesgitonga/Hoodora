// Sending an action, then refreshing whatever shows its effect.

import { useCustomMutation, useInvalidate } from "@refinedev/core";
import { App } from "antd";

export function useAction() {
  const { mutateAsync } = useCustomMutation();
  const invalidate = useInvalidate();
  const { message } = App.useApp();

  return async function act(
    url: string,
    values: Record<string, unknown>,
    { done, refresh, method = "post" }: { done: string; refresh: string[]; method?: "post" | "patch" | "delete" },
  ) {
    // Errors go back to the dialog, which shows them and stays open.
    const result = await mutateAsync({ url, method, values, successNotification: false, errorNotification: false });
    await Promise.all(refresh.map((resource) => invalidate({ resource, invalidates: ["all"] })));
    void message.success(done);
    return result.data;
  };
}
