const bridge = window.AstrBotPluginPage;

// ===== 多语言 =====
const i18n = {
    zh: {
        overview: "总览",
        users: "用户管理",
        records: "签到记录",
        refresh: "刷新",
        loading: "加载中",
        empty: "暂无数据",
        totalUsers: "总用户数",
        totalPoints: "总积分",
        todaySignins: "今日签到",
        active7d: "7日活跃",
        active30d: "30日活跃",
        rank: "积分排行",
        recent: "最近签到",
        userList: "用户列表",
        signinRecords: "签到记录",
        search: "搜索用户...",
        count: "共 {n} 人",
        editPoints: "修改积分",
        add: "增加积分",
        deduct: "扣除积分",
        amount: "数量",
        cancel: "取消",
        confirm: "确认",
        user: "用户",
        date: "日期",
        points: "积分",
        streak: "连续",
        totalSignins: "累计签到",
        items: "道具",
        action: "操作",
        modifyPoints: "修改积分",
        success: "操作成功",
        error: "操作失败",
        themeLight: "切换为夜间模式",
        themeDark: "切换为日间模式",
    },
    en: {
        overview: "Overview",
        users: "Users",
        records: "Records",
        refresh: "Refresh",
        loading: "Loading",
        empty: "No data",
        totalUsers: "Total Users",
        totalPoints: "Total Points",
        todaySignins: "Today",
        active7d: "7 Days",
        active30d: "30 Days",
        rank: "Rank",
        recent: "Recent",
        userList: "User List",
        signinRecords: "Sign-in Records",
        search: "Search users...",
        count: "{n} users",
        editPoints: "Edit Points",
        add: "Add Points",
        deduct: "Deduct Points",
        amount: "Amount",
        cancel: "Cancel",
        confirm: "Confirm",
        user: "User",
        date: "Date",
        points: "Points",
        streak: "Streak",
        totalSignins: "Total Sign-ins",
        items: "Items",
        action: "Action",
        modifyPoints: "Modify Points",
        success: "Success",
        error: "Error",
        themeLight: "Switch to dark mode",
        themeDark: "Switch to light mode",
    }
};

// ===== 状态 =====
const state = {
    lang: "zh",
    theme: "light",
    currentTab: "overview",
    allUsers: [],
    filteredUsers: [],
    selectedUser: null,
};

function t(key, ...args) {
    let text = i18n[state.lang][key] || key;
    args.forEach((arg, i) => {
        text = text.replace(`{${i}}`, arg).replace("{n}", arg);
    });
    return text;
}

// ===== 初始化 =====
async function init() {
    const context = await bridge.ready();

    // 检测主题
    if (context.isDark) {
        state.theme = "dark";
        document.documentElement.setAttribute("data-theme", "dark");
    }

    bindEvents();
    await loadData();
    updateUI();
}

function bindEvents() {
    // 导航切换
    document.querySelectorAll(".nav-item").forEach(btn => {
        btn.addEventListener("click", () => switchTab(btn.dataset.tab));
    });

    // 刷新
    document.getElementById("refresh-btn").addEventListener("click", async function() {
        this.disabled = true;
        await loadData();
        this.disabled = false;
    });

    // 搜索
    document.getElementById("user-search").addEventListener("input", debounce(filterUsers, 250));

    // 主题切换
    document.getElementById("theme-toggle").addEventListener("click", toggleTheme);

    // 语言切换
    document.getElementById("lang-toggle").addEventListener("click", toggleLang);

    // 弹窗
    document.getElementById("modal-close").addEventListener("click", closeModal);
    document.getElementById("modal-cancel").addEventListener("click", closeModal);
    document.getElementById("modal-confirm").addEventListener("click", confirmPointsUpdate);
    document.getElementById("points-modal").addEventListener("click", e => {
        if (e.target === document.getElementById("points-modal")) closeModal();
    });
}

// ===== 标签页切换 =====
function switchTab(tab) {
    state.currentTab = tab;
    document.querySelectorAll(".nav-item").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.tab === tab);
    });
    document.querySelectorAll(".tab-panel").forEach(panel => {
        panel.classList.toggle("active", panel.id === `panel-${tab}`);
    });
    updateTitle();
}

function updateTitle() {
    const titles = { overview: "overview", users: "users", records: "records" };
    document.getElementById("page-title").textContent = t(titles[state.currentTab]);
}

// ===== 数据加载 =====
async function loadData() {
    try {
        const data = await bridge.apiGet("admin/data");
        renderOverview(data.overview, data.leaderboard, data.recent_signins);
        state.allUsers = data.users;
        state.filteredUsers = [...state.allUsers];
        renderUsers();
        renderRecords(data.recent_signins);
    } catch (err) {
        console.error("加载数据失败:", err);
        showToast(t("error") + ": " + err.message, "error");
    }
}

// ===== 渲染总览 =====
function renderOverview(overview, leaderboard, recent) {
    document.getElementById("ov-users").textContent = fmtNum(overview.total_users);
    document.getElementById("ov-points").textContent = fmtNum(overview.total_points);
    document.getElementById("ov-today").textContent = fmtNum(overview.today_signins);
    document.getElementById("ov-7d").textContent = fmtNum(overview.active_7d);
    document.getElementById("ov-30d").textContent = fmtNum(overview.active_30d);

    const rankBody = document.getElementById("ov-rank-body");
    rankBody.innerHTML = "";
    if (leaderboard && leaderboard.length > 0) {
        leaderboard.slice(0, 10).forEach(u => {
            const badge = u.rank <= 3 ? ["🥇", "🥈", "🥉"][u.rank - 1] : u.rank;
            rankBody.innerHTML += `
                <tr>
                    <td style="text-align:center;font-weight:600;width:50px">${badge}</td>
                    <td>${esc(u.nickname)}</td>
                    <td style="font-weight:600;color:var(--primary)">${fmtNum(u.points)}</td>
                    <td><span class="tag">${u.streak}${state.lang === "zh" ? "天" : "d"}</span></td>
                </tr>
            `;
        });
    } else {
        rankBody.innerHTML = `<tr><td colspan="4" class="empty">${t("empty")}</td></tr>`;
    }

    const recentBody = document.getElementById("ov-recent-body");
    recentBody.innerHTML = "";
    if (recent && recent.length > 0) {
        recent.slice(0, 10).forEach(r => {
            recentBody.innerHTML += `
                <tr>
                    <td>${esc(r.nickname || r.user_id)}</td>
                    <td>${r.date}</td>
                    <td><span class="tag">${r.streak}${state.lang === "zh" ? "天" : "d"}</span></td>
                </tr>
            `;
        });
    } else {
        recentBody.innerHTML = `<tr><td colspan="3" class="empty">${t("empty")}</td></tr>`;
    }
}

// ===== 渲染用户列表 =====
function renderUsers() {
    const tbody = document.getElementById("users-tbody");
    const users = state.filteredUsers;
    document.getElementById("user-count").textContent = t("count", users.length);

    tbody.innerHTML = "";
    if (users.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" class="empty">${t("empty")}</td></tr>`;
        return;
    }

    users.forEach((u, idx) => {
        const items = u.items.join(", ");
        tbody.innerHTML += `
            <tr>
                <td style="text-align:center;color:var(--text-secondary)">${idx + 1}</td>
                <td><code style="font-size:11px">${esc(u.user_id)}</code></td>
                <td><strong>${esc(u.nickname)}</strong></td>
                <td style="font-weight:600;color:var(--primary)">${fmtNum(u.points)}</td>
                <td>${u.total_signins}</td>
                <td><span class="tag">${u.streak}${state.lang === "zh" ? "天" : "d"}</span></td>
                <td style="font-size:12px;color:var(--text-secondary)">${esc(items)}</td>
                <td><button class="btn-edit" onclick="openPointsModal('${esc(u.user_id)}', '${esc(u.nickname)}', ${u.points})">${t("editPoints")}</button></td>
            </tr>
        `;
    });
}

// ===== 渲染签到记录 =====
function renderRecords(records) {
    const tbody = document.getElementById("records-tbody");
    tbody.innerHTML = "";
    if (records && records.length > 0) {
        records.forEach((r, idx) => {
            tbody.innerHTML += `
                <tr>
                    <td style="text-align:center;color:var(--text-secondary)">${idx + 1}</td>
                    <td>${esc(r.nickname || r.user_id)}</td>
                    <td>${r.date}</td>
                    <td style="font-weight:600;color:var(--primary)">+${fmtNum(r.points)}</td>
                    <td><span class="tag">${r.streak}${state.lang === "zh" ? "天" : "d"}</span></td>
                </tr>
            `;
        });
    } else {
        tbody.innerHTML = `<tr><td colspan="5" class="empty">${t("empty")}</td></tr>`;
    }
}

// ===== 搜索过滤 =====
function filterUsers() {
    const keyword = document.getElementById("user-search").value.trim().toLowerCase();
    if (!keyword) {
        state.filteredUsers = [...state.allUsers];
    } else {
        state.filteredUsers = state.allUsers.filter(u =>
            u.user_id.toLowerCase().includes(keyword) ||
            u.nickname.toLowerCase().includes(keyword)
        );
    }
    renderUsers();
}

// ===== 主题切换 =====
function toggleTheme() {
    state.theme = state.theme === "light" ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", state.theme);
    document.getElementById("theme-toggle").title = state.theme === "light" ? t("themeLight") : t("themeDark");
}

// ===== 语言切换 =====
function toggleLang() {
    state.lang = state.lang === "zh" ? "en" : "zh";
    updateUI();
    renderUsers();
    updateTitle();
}

function updateUI() {
    document.getElementById("user-search").placeholder = t("search");
    document.getElementById("refresh-btn").querySelector("span").textContent = t("refresh");
    document.getElementById("theme-toggle").title = state.theme === "light" ? t("themeLight") : t("themeDark");

    // 更新表头
    const headers = document.querySelectorAll(".simple-table th");
    headers.forEach(h => {
        const text = h.textContent.trim();
        if (text === "排名" || text === "Rank") h.textContent = state.lang === "zh" ? "排名" : "Rank";
        if (text === "用户" || text === "User") h.textContent = state.lang === "zh" ? "用户" : "User";
        if (text === "积分" || text === "Points") h.textContent = state.lang === "zh" ? "积分" : "Points";
        if (text === "连续" || text === "Streak") h.textContent = state.lang === "zh" ? "连续" : "Streak";
        if (text === "日期" || text === "Date") h.textContent = state.lang === "zh" ? "日期" : "Date";
        if (text === "累计签到" || text === "Total") h.textContent = state.lang === "zh" ? "累计签到" : "Total";
        if (text === "道具" || text === "Items") h.textContent = state.lang === "zh" ? "道具" : "Items";
        if (text === "操作" || text === "Action") h.textContent = state.lang === "zh" ? "操作" : "Action";
    });
}

// ===== 积分修改弹窗 =====
window.openPointsModal = function(userId, nickname, points) {
    state.selectedUser = { userId, nickname, points };
    const info = document.getElementById("modal-user-info");
    info.innerHTML = `
        ${esc(nickname)}<br>
        <code>${esc(userId)}</code><br>
        ${state.lang === "zh" ? "当前积分" : "Current"}: <strong style="color:var(--primary)">${fmtNum(points)}</strong>
    `;
    document.getElementById("modal-action").innerHTML = `
        <option value="add">${t("add")}</option>
        <option value="deduct">${t("deduct")}</option>
    `;
    document.getElementById("modal-amount").value = "10";
    document.getElementById("points-modal").classList.add("show");
};

function closeModal() {
    document.getElementById("points-modal").classList.remove("show");
    state.selectedUser = null;
}

async function confirmPointsUpdate() {
    if (!state.selectedUser) return;
    const action = document.getElementById("modal-action").value;
    const amount = parseInt(document.getElementById("modal-amount").value);
    if (!amount || amount <= 0) {
        showToast("请输入有效的数量", "error");
        return;
    }

    try {
        await bridge.apiPost(`admin/user/${state.selectedUser.userId}/points`, {
            action, amount
        });
        closeModal();
        showToast(t("success"), "success");
        await loadData();
    } catch (err) {
        showToast(t("error") + ": " + err.message, "error");
    }
}

// ===== 工具函数 =====
function fmtNum(n) {
    return n?.toLocaleString?.() || n || "0";
}

function esc(text) {
    if (!text) return "";
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

function debounce(fn, delay) {
    let timer;
    return function(...args) {
        clearTimeout(timer);
        timer = setTimeout(() => fn.apply(this, args), delay);
    };
}

function showToast(message, type = "info") {
    const toast = document.createElement("div");
    toast.style.cssText = `
        position: fixed; top: 20px; right: 20px; z-index: 9999;
        padding: 12px 20px; border-radius: 8px; font-size: 14px;
        color: #fff; box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        animation: slideIn 0.3s ease;
    `;
    toast.style.background = type === "success" ? "var(--success)" : type === "error" ? "var(--error)" : "var(--primary)";
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => {
        toast.style.animation = "slideOut 0.3s ease forwards";
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// 动态添加动画样式
const animStyle = document.createElement("style");
animStyle.textContent = `
    @keyframes slideIn { from { transform: translateX(100px); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
    @keyframes slideOut { from { transform: translateX(0); opacity: 1; } to { transform: translateX(100px); opacity: 0; } }
    .tag { display: inline-block; padding: 2px 8px; background: var(--primary-light); color: var(--primary); border-radius: 4px; font-size: 12px; font-weight: 500; }
`;
document.head.appendChild(animStyle);

// 启动
init();
