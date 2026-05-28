const state = {
  data: null,
  hospitals: [],
  filtered: [],
};

const unavailableValue = "公開情報なし";

const elements = {
  datasetYear: document.querySelector("#datasetYear"),
  totalCount: document.querySelector("#totalCount"),
  visibleCount: document.querySelector("#visibleCount"),
  keyword: document.querySelector("#keyword"),
  excludeKeyword: document.querySelector("#excludeKeyword"),
  typeFilter: document.querySelector("#typeFilter"),
  regionFilter: document.querySelector("#regionFilter"),
  prefectureFilter: document.querySelector("#prefectureFilter"),
  emergencyFilter: document.querySelector("#emergencyFilter"),
  participationFilter: document.querySelector("#participationFilter"),
  quotaMin: document.querySelector("#quotaMin"),
  quotaMax: document.querySelector("#quotaMax"),
  sortOrder: document.querySelector("#sortOrder"),
  toggleAdvancedFilters: document.querySelector("#toggleAdvancedFilters"),
  advancedFilters: document.querySelector("#advancedFilters"),
  activeFilters: document.querySelector("#activeFilters"),
  filterSummary: document.querySelector("#filterSummary"),
  resetFilters: document.querySelector("#resetFilters"),
  downloadCsv: document.querySelector("#downloadCsv"),
  noticeText: document.querySelector("#noticeText"),
  resultsBody: document.querySelector("#resultsBody"),
  emptyState: document.querySelector("#emptyState"),
  sourceList: document.querySelector("#sourceList"),
};

const prefectureOrder = [
  "北海道",
  "青森",
  "岩手",
  "宮城",
  "秋田",
  "山形",
  "福島",
  "茨城",
  "栃木",
  "群馬",
  "埼玉",
  "千葉",
  "東京",
  "神奈川",
  "新潟",
  "富山",
  "石川",
  "福井",
  "山梨",
  "長野",
  "岐阜",
  "静岡",
  "愛知",
  "三重",
  "滋賀",
  "京都",
  "大阪",
  "兵庫",
  "奈良",
  "和歌山",
  "鳥取",
  "島根",
  "岡山",
  "広島",
  "山口",
  "徳島",
  "香川",
  "愛媛",
  "高知",
  "福岡",
  "佐賀",
  "長崎",
  "熊本",
  "大分",
  "宮崎",
  "鹿児島",
  "沖縄",
];

const regionOrder = [
  "北海道",
  "東北",
  "関東",
  "中部",
  "近畿",
  "中国",
  "四国",
  "九州・沖縄",
];

function uniqueValues(items, key, preferredOrder = null) {
  const values = [...new Set(items.map((item) => item[key]))];
  if (!preferredOrder) {
    return values.sort((a, b) => a.localeCompare(b, "ja"));
  }
  return preferredOrder.filter((value) => values.includes(value));
}

function fillSelect(select, values) {
  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.append(option);
  });
}

function fillMultiSelect(select, values, selectedValues = []) {
  const selectedSet = new Set(selectedValues);
  select.replaceChildren();
  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    option.selected = selectedSet.has(value);
    select.append(option);
  });
}

function getSelectedValues(select) {
  return [...select.selectedOptions].map((option) => option.value);
}

function selectedLabels(select) {
  return [...select.selectedOptions].map((option) => option.textContent);
}

function normalize(value) {
  return String(value ?? "").toLowerCase().normalize("NFKC").trim();
}

function emergencyLevel(value) {
  const normalized = normalize(value);
  if (normalized.startsWith("1次救急")) return "1";
  if (normalized.startsWith("2次救急")) return "2";
  if (normalized.startsWith("3次救急")) return "3";
  return "";
}

function parseNumberFilter(value) {
  const number = Number(value);
  return Number.isFinite(number) && value !== "" ? number : null;
}

function quotaNumber(value) {
  if (!value || value === unavailableValue) return null;
  const match = normalize(value).match(/\d+/);
  return match ? Number(match[0]) : null;
}

function getFilters() {
  return {
    keyword: normalize(elements.keyword.value),
    excludeKeywords: normalize(elements.excludeKeyword.value)
      .split(/\s+/)
      .filter(Boolean),
    type: elements.typeFilter.value,
    regions: getSelectedValues(elements.regionFilter),
    prefectures: getSelectedValues(elements.prefectureFilter),
    emergencyLevels: getSelectedValues(elements.emergencyFilter),
    participation: elements.participationFilter.value,
    quotaMin: parseNumberFilter(elements.quotaMin.value),
    quotaMax: parseNumberFilter(elements.quotaMax.value),
    sortOrder: elements.sortOrder.value,
  };
}

function compareByPrefecture(a, b) {
  const prefDiff =
    prefectureOrder.indexOf(a.prefecture) - prefectureOrder.indexOf(b.prefecture);
  if (prefDiff !== 0) return prefDiff;
  if (a.type !== b.type) return a.type.localeCompare(b.type, "ja");
  return a.receptionNumber - b.receptionNumber;
}

function sortHospitals(items, sortOrder) {
  const sorted = [...items];
  if (sortOrder === "name") {
    sorted.sort((a, b) => a.name.localeCompare(b.name, "ja"));
  } else if (sortOrder === "number") {
    sorted.sort((a, b) => a.receptionNumber - b.receptionNumber);
  } else {
    sorted.sort(compareByPrefecture);
  }
  return sorted;
}

function filterHospitals() {
  const filters = getFilters();
  const filtered = state.hospitals.filter((hospital) => {
    const quota = quotaNumber(hospital.quota);
    const keywordTarget = normalize(
      `${hospital.name} ${hospital.prefecture} ${hospital.region} ${hospital.type} ${hospital.receptionNumber} ${hospital.emergencyCategory} ${hospital.salary} ${hospital.quota} ${hospital.beds}`,
    );

    return (
      (!filters.keyword || keywordTarget.includes(filters.keyword)) &&
      !filters.excludeKeywords.some((keyword) => keywordTarget.includes(keyword)) &&
      (!filters.type || hospital.type === filters.type) &&
      (!filters.regions.length || filters.regions.includes(hospital.region)) &&
      (!filters.prefectures.length || filters.prefectures.includes(hospital.prefecture)) &&
      (!filters.emergencyLevels.length ||
        filters.emergencyLevels.includes(emergencyLevel(hospital.emergencyCategory))) &&
      (!filters.participation ||
        String(hospital.matchingParticipation) === filters.participation) &&
      (filters.quotaMin === null || (quota !== null && quota >= filters.quotaMin)) &&
      (filters.quotaMax === null || (quota !== null && quota <= filters.quotaMax))
    );
  });

  state.filtered = sortHospitals(filtered, filters.sortOrder);
  renderResults();
  renderFilterState(filters);
}

function addChip(fragment, label) {
  const chip = document.createElement("span");
  chip.className = "filter-chip";
  chip.textContent = label;
  fragment.append(chip);
}

function renderFilterState(filters) {
  const fragment = document.createDocumentFragment();
  const selectedRegions = selectedLabels(elements.regionFilter);
  const selectedPrefectures = selectedLabels(elements.prefectureFilter);
  const selectedEmergencyLevels = selectedLabels(elements.emergencyFilter);
  let activeCount = 0;

  const add = (condition, label) => {
    if (!condition) return;
    activeCount += 1;
    addChip(fragment, label);
  };

  add(filters.keyword, `検索: ${elements.keyword.value.trim()}`);
  add(filters.excludeKeywords.length, `除外: ${elements.excludeKeyword.value.trim()}`);
  add(filters.type, `区分: ${filters.type}`);
  add(filters.participation, `参加: ${elements.participationFilter.selectedOptions[0].textContent}`);
  add(filters.quotaMin !== null || filters.quotaMax !== null, `定員: ${filters.quotaMin ?? 0}〜${filters.quotaMax ?? "上限なし"}名`);
  add(selectedRegions.length, `地方: ${selectedRegions.join("、")}`);
  add(selectedPrefectures.length, `都道府県: ${selectedPrefectures.join("、")}`);
  add(selectedEmergencyLevels.length, `救急: ${selectedEmergencyLevels.join("、")}`);

  elements.activeFilters.replaceChildren(fragment);
  elements.activeFilters.hidden = activeCount === 0;
  elements.filterSummary.textContent = activeCount
    ? `${activeCount}条件で絞り込み中`
    : "全件表示中";
}

function setAdvancedFiltersExpanded(expanded) {
  elements.advancedFilters.hidden = !expanded;
  elements.toggleAdvancedFilters.setAttribute("aria-expanded", String(expanded));
  elements.toggleAdvancedFilters.textContent = expanded
    ? "詳細条件を閉じる"
    : "詳細条件を開く";
}

function createCell(text, className = "") {
  const cell = document.createElement("td");
  if (className) cell.className = className;
  cell.textContent = text;
  return cell;
}

function createHospitalCell(hospital) {
  const cell = document.createElement("td");
  const link = document.createElement("a");
  link.href = hospital.hospitalUrl;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = hospital.name;
  cell.append(link);
  return cell;
}

function createDetailCell(value, populatedClass = "") {
  const isUnavailable = value === unavailableValue;
  return createCell(value || "未取得", value && !isUnavailable ? populatedClass : "muted-cell");
}

function renderResults() {
  const fragment = document.createDocumentFragment();
  state.filtered.forEach((hospital) => {
    const row = document.createElement("tr");
    row.append(
      createCell(hospital.prefecture),
      createHospitalCell(hospital),
      createCell(hospital.type),
      createCell(hospital.region),
      createDetailCell(hospital.emergencyCategory),
      createDetailCell(hospital.salary, "salary-cell"),
      createDetailCell(hospital.quota, "number-cell"),
      createDetailCell(hospital.beds, "number-cell"),
    );

    const statusCell = document.createElement("td");
    statusCell.className = "status-cell";
    const status = document.createElement("span");
    status.className = hospital.matchingParticipation
      ? "status-badge"
      : "status-badge is-off";
    status.textContent = hospital.matchingParticipation ? "参加" : "不参加";
    statusCell.append(status);
    row.append(statusCell, createCell(hospital.receptionNumber, "number-cell"));
    fragment.append(row);
  });

  elements.resultsBody.replaceChildren(fragment);
  elements.visibleCount.textContent = state.filtered.length.toLocaleString("ja-JP");
  elements.emptyState.hidden = state.filtered.length > 0;
}

function renderSources() {
  const fragment = document.createDocumentFragment();
  state.data.sources.forEach((source) => {
    const item = document.createElement("li");
    const link = document.createElement("a");
    link.href = source.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = source.label;
    item.append(link);
    fragment.append(item);
  });
  elements.sourceList.replaceChildren(fragment);
}

function resetPrefectureOptions(prefectures = state.hospitals.map((hospital) => hospital.prefecture)) {
  const availablePrefectures = prefectureOrder.filter((prefecture) =>
    prefectures.includes(prefecture),
  );
  const selectedPrefectures = getSelectedValues(elements.prefectureFilter).filter((prefecture) =>
    availablePrefectures.includes(prefecture),
  );
  fillMultiSelect(elements.prefectureFilter, availablePrefectures, selectedPrefectures);
}

function syncPrefectureOptions() {
  const selectedRegions = getSelectedValues(elements.regionFilter);
  const prefectures = selectedRegions.length
    ? state.hospitals
        .filter((hospital) => selectedRegions.includes(hospital.region))
        .map((hospital) => hospital.prefecture)
    : state.hospitals.map((hospital) => hospital.prefecture);

  resetPrefectureOptions(prefectures);
}

function downloadCsv() {
  const header = [
    "年度",
    "都道府県",
    "地方",
    "病院名",
    "病院区分",
    "救急区分",
    "給与",
    "募集定員",
    "病床数",
    "マッチング参加",
    "受付番号",
    "病院URL",
    "出典URL",
    "レジナビURL",
  ];
  const rows = state.filtered.map((hospital) => [
    hospital.year,
    hospital.prefecture,
    hospital.region,
    hospital.name,
    hospital.type,
    hospital.emergencyCategory,
    hospital.salary,
    hospital.quota,
    hospital.beds,
    hospital.matchingParticipation ? "参加" : "不参加",
    hospital.receptionNumber,
    hospital.hospitalUrl,
    hospital.sourceUrl,
    hospital.reginaviSourceUrl || "",
  ]);
  const csv = [header, ...rows]
    .map((row) =>
      row
        .map((value) => `"${String(value).replaceAll('"', '""')}"`)
        .join(","),
    )
    .join("\n");

  const blob = new Blob([`\ufeff${csv}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "jrmp-hospitals-2025.csv";
  link.click();
  URL.revokeObjectURL(url);
}

function resetFilters() {
  elements.keyword.value = "";
  elements.excludeKeyword.value = "";
  elements.typeFilter.value = "";
  [...elements.regionFilter.options].forEach((option) => {
    option.selected = false;
  });
  resetPrefectureOptions();
  [...elements.prefectureFilter.options].forEach((option) => {
    option.selected = false;
  });
  [...elements.emergencyFilter.options].forEach((option) => {
    option.selected = false;
  });
  elements.participationFilter.value = "";
  elements.quotaMin.value = "";
  elements.quotaMax.value = "";
  elements.sortOrder.value = "prefecture";
  filterHospitals();
}

function bindEvents() {
  [
    elements.keyword,
    elements.excludeKeyword,
    elements.typeFilter,
    elements.regionFilter,
    elements.prefectureFilter,
    elements.emergencyFilter,
    elements.participationFilter,
    elements.quotaMin,
    elements.quotaMax,
    elements.sortOrder,
  ].forEach((element) => {
    element.addEventListener("input", filterHospitals);
  });

  elements.regionFilter.addEventListener("input", () => {
    syncPrefectureOptions();
    filterHospitals();
  });

  elements.toggleAdvancedFilters.addEventListener("click", () => {
    const expanded =
      elements.toggleAdvancedFilters.getAttribute("aria-expanded") === "true";
    setAdvancedFiltersExpanded(!expanded);
  });

  elements.resetFilters.addEventListener("click", resetFilters);
  elements.downloadCsv.addEventListener("click", downloadCsv);
}

async function init() {
  try {
    const response = await fetch(`data/hospitals.json?v=${Date.now()}`, {
      cache: "no-store",
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    state.data = await response.json();
    state.hospitals = state.data.hospitals;
    elements.datasetYear.textContent = `${state.data.datasetYear}年度`;
    elements.totalCount.textContent = state.hospitals.length.toLocaleString("ja-JP");
    elements.noticeText.textContent = `${state.data.notice} データ生成日: ${state.data.generatedAt}`;

    fillSelect(elements.typeFilter, uniqueValues(state.hospitals, "type"));
    fillMultiSelect(
      elements.regionFilter,
      uniqueValues(state.hospitals, "region", regionOrder),
    );
    fillMultiSelect(
      elements.prefectureFilter,
      uniqueValues(state.hospitals, "prefecture", prefectureOrder),
    );
    renderSources();
    bindEvents();
    filterHospitals();
  } catch (error) {
    elements.noticeText.textContent =
      "データの読み込みに失敗しました。GitHub Pagesではなくローカルファイルとして開いている場合は、簡易サーバー経由で表示してください。";
    console.error(error);
  }
}

init();
