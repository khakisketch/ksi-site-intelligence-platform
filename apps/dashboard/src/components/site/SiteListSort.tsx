"use client";

/** 정렬만 즉시 적용한다. 아직 제출하지 않은 검색어와 적용된 검색 조건을 섞지 않는다.
 * GET 폼이라 URL·뒤로가기 계약을 유지하고, JS가 없으면 제출 버튼으로 같은 일을 한다. */
export function SiteListSort({ sort, query, group, status }: {
  sort: string;
  query?: string;
  group?: string;
  status?: string;
}) {
  return (
    <form action="/sites" className="flex items-center gap-2">
      {query && <input type="hidden" name="q" value={query} />}
      {group && <input type="hidden" name="group" value={group} />}
      {status && <input type="hidden" name="status" value={status} />}
      <label className="flex items-center gap-2 text-[12px] font-medium text-ink-2">
        정렬
        <select key={sort} name="sort" defaultValue={sort} aria-label="정렬 기준" className="input h-11 w-36 text-[12.5px]" onChange={(event) => event.currentTarget.form?.requestSubmit()}>
          <option value="attention">확인 필요 순</option>
          <option value="updated">최근 갱신 순</option>
          <option value="name">이름 순</option>
        </select>
      </label>
      <noscript><button type="submit" className="btn tap-target">정렬 적용</button></noscript>
    </form>
  );
}
