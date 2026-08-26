export interface SiteThumbnailImage {
  src: string;
  alt: string;
}

interface SiteThumbnailProps {
  siteId: string;
  siteName: string;
  image: SiteThumbnailImage | null;
  className?: string;
  loading?: "eager" | "lazy";
  /** 작은 표 썸네일에서는 긴 안내문을 시각적으로 숨기되 접근 가능한 이름은 유지한다. */
  compact?: boolean;
}

function siteVariant(siteId: string): number {
  return [...siteId].reduce((sum, character) => sum + character.charCodeAt(0), 0) % 3;
}

/**
 * 현장 목록과 홈이 공유하는 정직한 썸네일 표면.
 *
 * Site 계약에는 아직 대표 이미지가 없다. 따라서 실제 Event evidence가 연결된 경우에만
 * 사진을 표시하고, 그렇지 않으면 현장마다 조금씩 다른 중립 도식을 보여 준다. 도식은
 * 촬영 결과나 공간모델로 오인되지 않도록 항상 `대표 이미지 없음`으로 명시한다(INV-040).
 */
export function SiteThumbnail({
  siteId,
  siteName,
  image,
  className = "",
  loading = "lazy",
  compact = false,
}: SiteThumbnailProps) {
  const variant = siteVariant(siteId);
  const linePath = [
    "m42 214 83-98 98 38 66-83 102 35 119-61",
    "m42 97 92 48 89-72 103 102 88-63 96 91",
    "m48 224 76-54 82 17 85-111 104 70 112-82",
  ][variant];
  const areaPath = [
    "m77 221 79-66 86 24 58-48 93 32 70-39 44 74-90 58-115-17-89 29Z",
    "m83 177 78-50 74 27 76-42 87 54 70-21 39 69-112 39-94-26-104 24Z",
    "m82 230 68-79 95 22 45-62 93 45 82-25 40 66-89 61-108-26-92 25Z",
  ][variant];

  return (
    <div
      data-site-thumbnail
      role="img"
      aria-label={image ? `${siteName} 최근 확인 항목 근거 이미지` : `${siteName} 대표 이미지 없음`}
      className={`relative isolate overflow-hidden bg-sunk ${className}`}
    >
      {image ? (
        <>
          {/* Presigned evidence URL은 정적 next/image host allowlist에 넣을 수 없다. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={image.src}
            alt={image.alt}
            loading={loading}
            referrerPolicy="no-referrer"
            className="absolute inset-0 size-full object-cover"
          />
          {!compact && (
            <span className="absolute right-2 bottom-2 rounded-sm bg-black/70 px-2 py-1 text-[10px] font-semibold text-white">
              최근 근거 이미지
            </span>
          )}
        </>
      ) : (
        <>
          <svg aria-hidden="true" viewBox="0 0 560 280" preserveAspectRatio="xMidYMid slice" className="absolute inset-0 size-full">
            <rect width="560" height="280" fill="var(--sunk)" />
            <path d="M0 56h560M0 112h560M0 168h560M0 224h560M112 0v280M224 0v280M336 0v280M448 0v280" stroke="var(--line)" />
            <path d={linePath} fill="none" stroke="var(--line-strong)" strokeWidth="2" />
            <path d={areaPath} fill="var(--surface)" fillOpacity="0.72" stroke="var(--line-strong)" strokeDasharray="7 7" />
            <circle cx={variant === 0 ? 302 : variant === 1 ? 376 : 246} cy={variant === 2 ? 173 : 158} r="7" fill="var(--accent)" />
          </svg>
          {!compact && (
            <span className="absolute right-2 bottom-2 rounded-sm border border-line-strong bg-surface/90 px-2 py-1 text-[10px] font-semibold text-ink-2 backdrop-blur-sm">
              대표 이미지 없음
            </span>
          )}
        </>
      )}
    </div>
  );
}
