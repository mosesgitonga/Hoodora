// Lists the API pages by cursor: newest or worst first, "Load more" for the rest.

import { useInfiniteList, type BaseRecord, type CrudFilters } from "@refinedev/core";
import { Button } from "antd";

export function useCursorList<T extends BaseRecord>(resource: string, filters: CrudFilters = []) {
  const { query, result } = useInfiniteList<T>({
    resource,
    filters,
    pagination: { pageSize: 25 },
    queryOptions: { retry: false },
  });
  const rows = (result.data?.pages ?? []).flatMap((page) => page.data);
  return {
    rows,
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    refetch: () => void query.refetch(),
    more: result.hasNextPage ? () => void query.fetchNextPage() : undefined,
    loadingMore: query.isFetchingNextPage,
  };
}

export function LoadMore({ more, loading }: { more?: () => void; loading: boolean }) {
  if (!more) return null;
  return (
    <div style={{ textAlign: "center", marginTop: 16 }}>
      <Button onClick={more} loading={loading}>
        Load more
      </Button>
    </div>
  );
}
