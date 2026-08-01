import React, { useEffect } from "react";

function Icon({ name }) {
  return (
    <span
      aria-hidden="true"
      dangerouslySetInnerHTML={{ __html: window.icon(name) }}
    />
  );
}

/** 管理列表共享分页（global-list-footer 视觉契约）。 */
export function Pagination({
  total,
  page,
  pageSize,
  onPage,
  onSize,
  id,
  countLabel = "条",
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const safePage = Math.min(page, pages);
  useEffect(() => {
    if (safePage !== page) onPage(safePage);
  }, [safePage, page, onPage]);
  return (
    <div className="global-list-footer management-list-footer" id={id}>
      <div className="global-page-summary">
        <span>
          共 {total} {countLabel}
        </span>
        <label>
          每页{" "}
          <select
            className="input global-page-size"
            aria-label="每页展示数量"
            value={pageSize}
            onChange={(e) => {
              onSize(Number(e.target.value));
              onPage(1);
            }}
          >
            {[10, 20, 50, 100].map((n) => (
              <option key={n}>{n}</option>
            ))}
          </select>
        </label>
      </div>
      <div className="global-pagination">
        <button
          type="button"
          aria-label="上一页"
          disabled={safePage <= 1}
          onClick={() => onPage(safePage - 1)}
        >
          <Icon name="previous" />
        </button>
        <span>
          {safePage} / {pages}
        </span>
        <button
          type="button"
          aria-label="下一页"
          disabled={safePage >= pages}
          onClick={() => onPage(safePage + 1)}
        >
          <Icon name="next" />
        </button>
      </div>
    </div>
  );
}
