import type { ArtifactSlot, GeoTiffRawHeader } from "@/lib/geo/geotiff-header";

/**
 * 올리기 전 점검: 브라우저가 읽은 첫 IFD 사실만으로 KSI 파일 검사(external_geotiff_inspector)가
 * 거부할 조건을 미리 알려 준다. 규칙은 그 검사기의 닫힌 프로필을 그대로 옮긴 것이다.
 *
 * 이것은 안내일 뿐 판정이 아니다. 판정은 등록 뒤 Core 검사만 만들고, 여기서는 아무것도 막지 않는다.
 * 그래서 확실히 거부되는 조건("blocked")과 파일 안쪽을 봐야 알 수 있는 조건("may")을 나눈다.
 * 헤더에 없는 사실은 모른다고 두고 점검을 만들지 않는다(추측 금지).
 */

export type PreflightLevel = "blocked" | "may" | "notice";

export type PreflightFinding = {
  code: string;
  level: PreflightLevel;
  /** 무엇이 문제인지 한 줄. */
  title: string;
  /** 어떻게 고치는지 한 줄. 고칠 수 없으면 null. */
  fix: string | null;
};

// 검사기 입력 상한의 절대값이다(external_validation_worker_config 의 2^31). 이보다 크면 정책과 무관하게 거부된다.
export const MAX_INSPECTABLE_BYTES = 2 ** 31;
// 체적 분석이 받는 투영좌표계(ksi_geo_spatial.crs.SUPPORTED_PROJECT_CRS).
const ANALYSIS_CRS = new Set(["EPSG:5179", "EPSG:5185", "EPSG:5186", "EPSG:5187", "EPSG:5188"]);
const USER_DEFINED = 32767;
const METRE = 9001;

const COMPRESSION_NAMES: Record<number, string> = {
  1: "무압축", 5: "LZW", 7: "JPEG", 8: "Deflate", 32946: "Deflate", 50000: "ZSTD",
  34712: "JPEG 2000", 34925: "LZMA", 32773: "PackBits", 34887: "LERC", 50001: "WebP",
};
const ORTHO_COMPRESSION = new Set([1, 5, 7, 8, 32946, 50000]);
const DSM_COMPRESSION = new Set([1, 5, 8, 32946, 50000]);

function compressionName(code: number): string {
  return COMPRESSION_NAMES[code] ?? `압축 코드 ${code}`;
}

function positive(value: unknown): number | null {
  const number = Array.isArray(value) ? value[0] : value;
  return typeof number === "number" && Number.isSafeInteger(number) && number > 0 ? number : null;
}

function epsgOf(geoKeys: Record<string, unknown> | null): { code: string | null; projected: boolean; geographic: boolean } {
  const projected = positive(geoKeys?.ProjectedCSTypeGeoKey);
  if (projected !== null && projected !== USER_DEFINED) return { code: `EPSG:${projected}`, projected: true, geographic: false };
  const geographic = positive(geoKeys?.GeographicTypeGeoKey);
  if (projected === null && geographic !== null && geographic !== USER_DEFINED) return { code: `EPSG:${geographic}`, projected: false, geographic: true };
  return { code: null, projected: false, geographic: false };
}

export function preflightGeoTiff(slot: ArtifactSlot, header: GeoTiffRawHeader, fileSize: number | null): PreflightFinding[] {
  const out: PreflightFinding[] = [];
  const add = (code: string, level: PreflightLevel, title: string, fix: string | null) => out.push({ code, level, title, fix });
  const layout = header.layout;
  const label = slot === "dsm" ? "DSM" : "정사영상";
  const bands = header.samplesPerPixel;

  if (fileSize !== null && fileSize > MAX_INSPECTABLE_BYTES) {
    add("FILE_TOO_LARGE", "blocked", "파일이 2 GiB를 넘어 검사할 수 없습니다.", "내보내기에서 작업구역만 잘라 내거나 해상도를 낮춰 2 GiB 이하로 만드세요.");
  }

  // 위치 정보
  if (layout) {
    const { code, projected, geographic } = epsgOf(header.geoKeys);
    if (!layout.georeferenced || header.geoKeys === null) {
      add("NO_GEOREFERENCE", "blocked", "파일에 위치·좌표계 정보가 들어 있지 않습니다.", "좌표가 포함된 GeoTIFF로 내보내세요. 별도 좌표 파일(.tfw, .prj)은 읽지 않습니다.");
    } else if (layout.modelType === 3) {
      add("GEOCENTRIC_CRS", "blocked", "지심 좌표계는 받지 않습니다.", "투영 좌표계(예: UTM, 중부원점)로 내보내세요.");
    } else if (code === null) {
      // 사용자 정의 좌표계도 투영 정의가 표준 좌표계와 일치하면 검사가 EPSG 로 확인할 수 있다
      // (실제 공개 DSM: ProjectedCSType=32767 이지만 GDA94 / MGA zone 50 = EPSG:28350 으로 확인됨). 그래서 막힘이 아니라 확인 필요로 둔다.
      add("NO_EPSG", "may", "파일에 EPSG 좌표계 번호가 직접 들어 있지 않습니다(사용자 정의 좌표계). 표준 좌표계로 확인되지 않으면 검사에서 거부됩니다.", "EPSG 번호가 파일에 기록되도록 내보내세요(예: EPSG:5186, UTM).");
    } else if (slot === "dsm" && geographic && !projected) {
      add("DSM_GEOGRAPHIC", "blocked", `DSM은 미터 단위 투영 좌표계여야 합니다. 이 파일은 위·경도(${code})입니다.`, "내보내기에서 투영 좌표계(예: UTM, 중부원점)를 고르세요.");
    } else if (slot === "dsm" && layout.projLinearUnits !== null && layout.projLinearUnits !== METRE) {
      add("DSM_UNIT_NOT_METRE", "may", "DSM 좌표 단위가 미터가 아닌 것으로 표시되어 있습니다.", "단위가 미터인 투영 좌표계로 내보내세요.");
    }
    if (slot === "dsm" && code !== null && projected && !ANALYSIS_CRS.has(code)) {
      add("CRS_NOT_ANALYSIS", "notice", `${code} 좌표계는 등록·표시는 되지만 체적 분석은 한국 좌표계(EPSG:5179, 5185~5188)에서만 합니다.`, "체적 분석이 필요하면 한국 좌표계로 내보내세요.");
    }
    if (slot === "dsm") {
      if (layout.verticalCsType === null) {
        add("NO_VERTICAL_REFERENCE", "notice", "파일에 수직 기준(높이 기준)이 없습니다. 등록한 뒤 자료 상세에서 수직 기준을 선언하면 높이·단면을 읽을 수 있습니다. 체적·두 시점 비교에는 쓸 수 없습니다.", "체적·비교가 필요하면 수직 기준이 포함된 좌표계(예: 지오이드 높이)로 내보내세요.");
      } else if (layout.verticalCsType === USER_DEFINED) {
        add("VERTICAL_USER_DEFINED", "may", "수직 기준이 EPSG 번호 없는 사용자 정의입니다.", "EPSG 번호가 있는 수직 기준으로 내보내세요.");
      } else if (layout.verticalUnits !== null && layout.verticalUnits !== METRE) {
        add("VERTICAL_UNIT_NOT_METRE", "may", "수직 기준의 단위가 미터가 아닌 것으로 표시되어 있습니다.", "높이 단위가 미터인 수직 기준으로 내보내세요.");
      }
    }
  }

  // 밴드·자료형
  if (bands > 4) {
    add("TOO_MANY_BANDS", "blocked", `밴드가 ${bands}개입니다. 4개 이하만 받습니다.`, `${label}에 필요한 밴드만 남겨 내보내세요.`);
  }
  if (layout && bands > 1 && layout.planarConfiguration !== 1) {
    add("PLANAR_SEPARATE", "blocked", "밴드가 분리 저장(plane 방식)된 파일은 받지 않습니다.", "픽셀 교차(pixel-interleaved) 방식으로 내보내세요.");
  }
  if (slot === "ortho") {
    const rgbModel = (bands === 3 || bands === 4) && header.bitsPerSample === 8 && header.sampleFormat === 1;
    if (!rgbModel && bands <= 4) {
      const kind = header.sampleFormat === 3 ? "실수" : header.sampleFormat === 2 ? "부호 있는 정수" : "정수";
      add("ORTHO_BAND_MODEL", "blocked", `정사영상은 8비트 RGB(또는 RGBA)여야 합니다. 이 파일은 ${header.bitsPerSample}비트 ${kind} ${bands}밴드입니다.`, "내보내기에서 8-bit RGB 정사영상으로 내보내세요.");
    }
    if (layout) {
      if (layout.hasNoDataTag) {
        add("ORTHO_NODATA", "blocked", "정사영상에 NoData 값이 지정되어 있습니다.", "NoData 지정 없이 내보내세요. 투명한 부분은 알파 밴드로 표현합니다.");
      }
      if (!ORTHO_COMPRESSION.has(layout.compression)) {
        add("ORTHO_COMPRESSION", "blocked", `정사영상 압축 방식(${compressionName(layout.compression)})을 받지 않습니다.`, "LZW, Deflate, ZSTD 중 하나이거나 무압축으로 내보내세요.");
      } else if (layout.compression === 7) {
        if (bands !== 3 || layout.photometric !== 6) {
          add("ORTHO_JPEG", "blocked", bands === 4 ? "투명도(알파)가 있는 정사영상은 JPEG 압축을 받지 않습니다." : "JPEG 압축 정사영상은 YCbCr 색 방식이어야 합니다.", "LZW나 Deflate 압축으로 내보내세요.");
        }
      } else if (layout.photometric !== 2) {
        add("ORTHO_PHOTOMETRIC", "blocked", "정사영상 색 방식이 RGB가 아닙니다.", "RGB 색 방식으로 내보내세요.");
      }
      if (ORTHO_COMPRESSION.has(layout.compression)) {
        const allowed = layout.compression === 1 || layout.compression === 7 ? [1] : [1, 2];
        if (!allowed.includes(layout.predictor)) {
          add("ORTHO_PREDICTOR", "blocked", "정사영상 압축 예측(predictor) 설정을 받지 않습니다.", "예측 설정 없이 내보내세요.");
        }
      }
      if (bands === 4) {
        add("ORTHO_ALPHA_BINARY", "notice", "투명도(알파)는 0 또는 255 값만 받습니다. 반투명 가장자리가 있으면 검사에서 거부됩니다.", "경계를 부드럽게 처리하지 않고 투명/불투명 두 값으로 내보내세요.");
        if (layout.extraSamples.length > 0 && layout.extraSamples[0] === 0) {
          add("ORTHO_ALPHA_UNSPECIFIED", "may", "네 번째 밴드가 투명도(알파)로 표시되어 있지 않습니다.", "네 번째 밴드를 알파로 지정해 내보내세요.");
        }
      }
    }
  } else {
    const floatModel = bands === 1 && header.sampleFormat === 3 && (header.bitsPerSample === 32 || header.bitsPerSample === 64);
    if (!floatModel && bands <= 4) {
      const kind = header.sampleFormat === 3 ? "실수" : header.sampleFormat === 2 ? "부호 있는 정수" : "정수";
      add("DSM_BAND_MODEL", "blocked", `DSM은 Float32 또는 Float64 한 밴드여야 합니다. 이 파일은 ${header.bitsPerSample}비트 ${kind} ${bands}밴드입니다.`, "내보내기에서 높이를 Float32 한 밴드로 저장하세요.");
    }
    if (layout) {
      if (!DSM_COMPRESSION.has(layout.compression)) {
        add("DSM_COMPRESSION", "blocked", `DSM 압축 방식(${compressionName(layout.compression)})을 받지 않습니다.`, "LZW, Deflate, ZSTD 중 하나이거나 무압축으로 내보내세요.");
      } else if (layout.predictor !== 1 && !(layout.compression !== 1 && layout.predictor === 3)) {
        add("DSM_PREDICTOR", "blocked", "DSM 압축 예측(predictor) 설정을 받지 않습니다.", "예측 없음 또는 실수용 예측(3)으로 내보내세요.");
      }
      if (layout.photometric !== 1) {
        add("DSM_PHOTOMETRIC", "blocked", "DSM 색 방식이 단일 밴드 흑백(MinIsBlack)이 아닙니다.", "한 밴드 높이 값으로 내보내세요.");
      }
      if ((layout.scale !== null && layout.scale !== 1) || (layout.offset !== null && layout.offset !== 0)) {
        add("DSM_SCALE_OFFSET", "blocked", "DSM 값에 배율(scale)이나 보정(offset)이 지정되어 있습니다.", "배율 1, 보정 0인 실제 높이 값으로 내보내세요.");
      }
    }
  }
  return out;
}

const LEVEL_ORDER: Record<PreflightLevel, number> = { blocked: 0, may: 1, notice: 2 };

export function sortFindings(findings: readonly PreflightFinding[]): PreflightFinding[] {
  return [...findings].sort((a, b) => LEVEL_ORDER[a.level] - LEVEL_ORDER[b.level]);
}

export function worstLevel(findings: readonly PreflightFinding[]): PreflightLevel | null {
  return findings.length === 0 ? null : sortFindings(findings)[0].level;
}
