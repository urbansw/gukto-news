(function () {
  const REGION_LABELS = {
    "": "전국", seoul: "서울", gyeonggi: "경기", incheon: "인천", gangwon: "강원",
    daejeon: "대전", sejong: "세종", chungbuk: "충북", chungnam: "충남",
    gwangju: "광주", jeonbuk: "전북", jeonnam: "전남", daegu: "대구",
    gyeongbuk: "경북", busan: "부산", ulsan: "울산", gyeongnam: "경남", jeju: "제주",
  };
  const REGION_ORDER = ["", "seoul", "gyeonggi", "incheon", "gangwon", "daejeon", "sejong",
    "chungbuk", "chungnam", "gwangju", "jeonbuk", "jeonnam", "daegu", "gyeongbuk",
    "busan", "ulsan", "gyeongnam", "jeju"];

  const state = { topic: "plan", region: "", query: "", shown: 15, cache: {} };
  const PAGE_SIZE = 15;

  const $ = (id) => document.getElementById(id);

  function buildRegionTabs() {
    const box = $("region-tabs");
    box.innerHTML = "";
    REGION_ORDER.forEach((code) => {
      const btn = document.createElement("button");
      btn.textContent = REGION_LABELS[code];
      btn.dataset.region = code;
      if (code === state.region) btn.classList.add("active");
      btn.addEventListener("click", () => {
        state.region = code;
        state.shown = PAGE_SIZE;
        [...box.children].forEach((b) => b.classList.toggle("active", b === btn));
        render();
      });
      box.appendChild(btn);
    });
  }

  function timeAgo(iso) {
    const d = new Date(iso);
    if (isNaN(d)) return "";
    const diffMs = Date.now() - d.getTime();
    const h = Math.floor(diffMs / 3600000);
    if (h < 1) return Math.max(1, Math.floor(diffMs / 60000)) + "분 전";
    if (h < 24) return h + "시간 전";
    const days = Math.floor(h / 24);
    if (days < 7) return days + "일 전";
    return d.toLocaleDateString("ko-KR", { year: "numeric", month: "2-digit", day: "2-digit" });
  }

  function filtered() {
    const items = state.cache[state.topic] || [];
    const q = state.query.trim();
    return items.filter((it) => {
      if (state.region && it.region !== state.region) return false;
      if (q && !it.title.includes(q)) return false;
      return true;
    });
  }

  function render() {
    const list = $("list");
    const all = filtered();
    const slice = all.slice(0, state.shown);
    list.innerHTML = "";

    if (slice.length === 0) {
      const li = document.createElement("li");
      li.className = "empty";
      li.textContent = "조건에 맞는 기사가 없습니다.";
      list.appendChild(li);
    }

    slice.forEach((it) => {
      const li = document.createElement("li");
      const a = document.createElement("a");
      a.className = "card";
      a.href = it.link;
      a.target = "_blank";
      a.rel = "noopener noreferrer";

      let avatar;
      if (it.image) {
        avatar = document.createElement("img");
        avatar.className = "card-thumb";
        avatar.src = it.image;
        avatar.loading = "lazy";
        avatar.alt = "";
        avatar.referrerPolicy = "no-referrer";
        avatar.addEventListener("error", () => {
          const fallback = document.createElement("div");
          fallback.className = "card-avatar";
          fallback.textContent = (it.source || "?").slice(0, 1);
          avatar.replaceWith(fallback);
        });
      } else {
        avatar = document.createElement("div");
        avatar.className = "card-avatar";
        avatar.textContent = (it.source || "?").slice(0, 1);
      }

      const body = document.createElement("div");
      body.className = "card-body";
      const title = document.createElement("p");
      title.className = "card-title";
      title.textContent = it.title;
      const meta = document.createElement("div");
      meta.className = "card-meta";
      if (it.region) {
        const badge = document.createElement("span");
        badge.className = "card-region";
        badge.textContent = REGION_LABELS[it.region] || it.region;
        meta.appendChild(badge);
      }
      const src = document.createElement("span");
      src.textContent = it.source || "출처 미상";
      const dot = document.createElement("span");
      dot.textContent = "·";
      const time = document.createElement("span");
      time.textContent = timeAgo(it.publishedAt);
      meta.append(src, dot, time);

      body.append(title, meta);
      a.append(avatar, body);
      li.appendChild(a);
      list.appendChild(li);
    });

    $("more-wrap").hidden = all.length <= state.shown;
  }

  async function loadTopic(topic) {
    if (state.cache[topic]) return;
    $("status").textContent = "불러오는 중…";
    $("status").className = "status";
    try {
      const res = await fetch("/api/news?topic=" + encodeURIComponent(topic));
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || "unknown error");
      state.cache[topic] = data.items;
      $("status").textContent = data.items.length + "건 불러옴";
    } catch (e) {
      state.cache[topic] = [];
      $("status").textContent = "기사를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.";
      $("status").className = "status err";
    }
  }

  function setupTopicTabs() {
    const box = $("topic-tabs");
    [...box.children].forEach((btn) => {
      btn.addEventListener("click", async () => {
        [...box.children].forEach((b) => b.classList.toggle("active", b === btn));
        state.topic = btn.dataset.topic;
        state.shown = PAGE_SIZE;
        await loadTopic(state.topic);
        render();
      });
    });
  }

  $("more-btn").addEventListener("click", () => {
    state.shown += PAGE_SIZE;
    render();
  });

  let searchTimer = null;
  $("search-input").addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.query = e.target.value;
      state.shown = PAGE_SIZE;
      render();
    }, 200);
  });

  (async function init() {
    buildRegionTabs();
    setupTopicTabs();
    await loadTopic(state.topic);
    render();
  })();
})();
