(function () {
  "use strict";

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.prototype.slice.call((root || document).querySelectorAll(sel));
  const page = document.body.dataset.page;

  function showToast(message) {
    const toast = $("#toast");
    if (!toast) return;
    toast.textContent = message;
    toast.classList.remove("hidden");
    clearTimeout(showToast._timer);
    showToast._timer = setTimeout(() => toast.classList.add("hidden"), 3200);
  }

  async function api(url, options) {
    const opts = options || {};
    const request = {
      method: opts.method || "GET",
      headers: { "Content-Type": "application/json" }
    };
    if (opts.body) request.body = JSON.stringify(opts.body);
    try {
      const response = await fetch(url, request);
      let data = null;
      try {
        data = await response.json();
      } catch (error) {
        data = { ok: false, error: "Сервер вернул некорректный ответ" };
      }
      if (!response.ok && !data.error) data.error = "Ошибка запроса";
      return data;
    } catch (error) {
      return { ok: false, error: "Нет связи с сервером" };
    }
  }

  function go(url) {
    window.location.href = url;
  }

  let audioCtx = null;

  function soundEnabled() {
    return document.documentElement.dataset.sound !== "off";
  }

  function playSound(kind) {
    if (!soundEnabled()) return;
    try {
      if (!audioCtx) {
        const Ctx = window.AudioContext || window.webkitAudioContext;
        if (!Ctx) return;
        audioCtx = new Ctx();
      }
      const ctx = audioCtx;
      if (ctx.state === "suspended") ctx.resume();
      const table = {
        move: { freq: 430, dur: 0.07, type: "triangle", vol: 0.08 },
        capture: { freq: 210, dur: 0.12, type: "square", vol: 0.06 },
        check: { freq: 740, dur: 0.16, type: "sine", vol: 0.09 },
        end: { freq: 320, dur: 0.32, type: "sine", vol: 0.1 }
      };
      const cfg = table[kind] || table.move;
      const now = ctx.currentTime;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = cfg.type;
      osc.frequency.setValueAtTime(cfg.freq, now);
      if (kind === "end") osc.frequency.exponentialRampToValueAtTime(150, now + cfg.dur);
      gain.gain.setValueAtTime(cfg.vol, now);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + cfg.dur);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(now);
      osc.stop(now + cfg.dur + 0.02);
    } catch (error) {
      /* звук не критичен */
    }
  }

  /* ---------------- index ---------------- */

  function initIndex() {
    const tabs = $$(".auth-tab");
    const loginForm = $("#login-form");
    const registerForm = $("#register-form");
    const recoverForm = $("#recover-form");
    const importForm = $("#import-form");
    const errorBox = $("#auth-error");
    const recoveryModal = $("#recovery-modal");
    const recoveryValue = $("#recovery-code-value");
    let pendingRedirect = "/menu";

    function showPanel(panel) {
      [loginForm, registerForm, recoverForm, importForm].forEach((form) => {
        if (form) form.classList.toggle("hidden", form !== panel);
      });
      errorBox.classList.add("hidden");
    }

    function showRecovery(code, redirect) {
      pendingRedirect = redirect || "/menu";
      if (!recoveryModal || !recoveryValue) {
        go(pendingRedirect);
        return;
      }
      recoveryValue.textContent = code || "—";
      recoveryModal.classList.remove("hidden");
    }

    function showError(message) {
      errorBox.textContent = message;
      errorBox.classList.remove("hidden");
    }

    tabs.forEach((tab) => {
      tab.addEventListener("click", () => {
        tabs.forEach((item) => item.classList.toggle("active", item === tab));
        showPanel(tab.dataset.tab === "login" ? loginForm : registerForm);
      });
    });

    const forgot = $("#forgot-btn");
    if (forgot) forgot.addEventListener("click", () => showPanel(recoverForm));
    const recoverBack = $("#recover-back");
    if (recoverBack) recoverBack.addEventListener("click", () => showPanel(loginForm));
    const importOpen = $("#import-open");
    if (importOpen) importOpen.addEventListener("click", () => showPanel(importForm));
    const importBack = $("#import-back");
    if (importBack) importBack.addEventListener("click", () => showPanel(loginForm));

    if (loginForm) {
      loginForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        errorBox.classList.add("hidden");
        const data = await api("/api/login", {
          method: "POST",
          body: {
            username: $("#login-username").value,
            password: $("#login-password").value,
            remember: $("#login-remember").checked
          }
        });
        if (data.ok) go(data.redirect || "/menu");
        else showError(data.error || "Не удалось войти");
      });
    }

    if (registerForm) {
      registerForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        errorBox.classList.add("hidden");
        const data = await api("/api/register", {
          method: "POST",
          body: {
            username: $("#register-username").value,
            password: $("#register-password").value,
            remember: $("#register-remember").checked
          }
        });
        if (data.ok) showRecovery(data.recovery_code, data.redirect);
        else showError(data.error || "Не удалось создать аккаунт");
      });
    }

    if (recoverForm) {
      recoverForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        errorBox.classList.add("hidden");
        const data = await api("/api/password/recover", {
          method: "POST",
          body: {
            username: $("#recover-username").value,
            code: $("#recover-code").value,
            new_password: $("#recover-password").value
          }
        });
        if (data.ok) showRecovery(data.recovery_code, data.redirect);
        else showError(data.error || "Не удалось восстановить пароль");
      });
    }

    if (importForm) {
      importForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        errorBox.classList.add("hidden");
        const fileInput = $("#import-file");
        const file = fileInput && fileInput.files ? fileInput.files[0] : null;
        if (!file) {
          showError("Выбери файл аккаунта");
          return;
        }
        let payload = null;
        try {
          payload = JSON.parse(await file.text());
        } catch (error) {
          showError("Файл не читается: нужен JSON из экспорта");
          return;
        }
        const data = await api("/api/account/import", {
          method: "POST",
          body: {
            payload: payload,
            username: $("#import-username").value,
            password: $("#import-password").value
          }
        });
        if (data.ok) showRecovery(data.recovery_code, data.redirect || "/menu");
        else showError(data.error || "Не удалось загрузить аккаунт");
      });
    }

    const copyRecovery = $("#copy-recovery");
    if (copyRecovery) {
      copyRecovery.addEventListener("click", async () => {
        const code = recoveryValue ? recoveryValue.textContent.trim() : "";
        if (!code || code === "—") return;
        try {
          await navigator.clipboard.writeText(code);
          copyRecovery.textContent = "Скопировано";
          setTimeout(() => {
            copyRecovery.textContent = "Скопировать";
          }, 1600);
        } catch (error) {
          showError("Скопируй код вручную: " + code);
        }
      });
    }

    const recoveryDone = $("#recovery-done");
    if (recoveryDone) {
      recoveryDone.addEventListener("click", () => go(pendingRedirect));
    }

    const skip = $("#skip-btn");
    if (skip) {
      skip.addEventListener("click", async () => {
        const data = await api("/api/skip", { method: "POST" });
        if (data.ok) go(data.redirect || "/menu");
        else showError(data.error || "Не удалось продолжить");
      });
    }

    const rememberYes = $("#remember-yes");
    if (rememberYes) {
      rememberYes.addEventListener("click", async () => {
        const data = await api("/api/remember", { method: "POST" });
        if (data.ok) go(data.redirect || "/menu");
        else showError(data.error || "Сохранённый вход не сработал");
      });
    }

    const rememberNo = $("#remember-no");
    if (rememberNo) {
      rememberNo.addEventListener("click", async () => {
        await api("/api/forget", { method: "POST" });
        $("#remember-modal").classList.add("hidden");
      });
    }

    $$("[data-close-modal]").forEach((button) => {
      button.addEventListener("click", () => {
        const overlay = button.closest(".modal-overlay");
        if (overlay) overlay.classList.add("hidden");
      });
    });
  }

  /* ---------------- coach ---------------- */

  function initCoach() {
    const coaches = window.COACHES || [];
    const selected = window.SELECTED_COACH || null;
    const cards = $$(".coach-card");
    const confirmBtn = $("#coach-confirm");
    const selectedLabel = $("#coach-selected-label");
    const modal = $("#coach-modal");
    const modalName = $("#coach-modal-name");
    const yesBtn = $("#coach-confirm-yes");
    let chosenId = null;

    function coachById(id) {
      return coaches.find((item) => Number(item.id) === Number(id));
    }

    function sample(coach) {
      return "Привет. Я " + coach.name + ", " + coach.role + ". " + coach.tagline +
        ". Давай разберём партию.";
    }

    function speak(coach) {
      if (!window.ChessVoice || !window.ChessVoice.available) {
        showToast("Озвучка недоступна в этом браузере");
        return;
      }
      window.ChessVoice.speak(sample(coach), coach);
    }

    function choose(id) {
      chosenId = Number(id);
      cards.forEach((card) => {
        card.classList.toggle("selected", Number(card.dataset.coachId) === chosenId);
      });
      const coach = coachById(chosenId);
      if (coach && selectedLabel) selectedLabel.textContent = "Выбран: " + coach.name;
      if (confirmBtn) confirmBtn.disabled = false;
    }

    cards.forEach((card) => {
      card.addEventListener("click", (event) => {
        if (event.target.closest(".coach-listen")) return;
        choose(card.dataset.coachId);
      });
      card.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          choose(card.dataset.coachId);
        }
      });
    });

    $$("[data-listen]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        const coach = coachById(button.dataset.listen);
        if (coach) speak(coach);
      });
    });

    const lockedListen = $("#coach-listen-locked");
    if (lockedListen && selected) {
      lockedListen.addEventListener("click", () => speak(selected));
    }

    if (confirmBtn) {
      confirmBtn.addEventListener("click", () => {
        const coach = coachById(chosenId);
        if (!coach) return;
        if (modalName) modalName.textContent = coach.name + " (" + coach.role + ")";
        if (modal) modal.classList.remove("hidden");
      });
    }

    if (yesBtn) {
      yesBtn.addEventListener("click", async () => {
        if (!chosenId) return;
        yesBtn.disabled = true;
        const data = await api("/api/coach/select", {
          method: "POST",
          body: { coach_id: chosenId }
        });
        if (data.ok) {
          go(data.redirect || "/menu");
        } else {
          showToast(data.error || "Не удалось выбрать тренера");
          yesBtn.disabled = false;
        }
      });
    }

    if (modal) {
      modal.querySelectorAll("[data-close-modal]").forEach((button) => {
        button.addEventListener("click", () => modal.classList.add("hidden"));
      });
    }

    if (window.ChessVoice) window.ChessVoice.refresh();
  }

  /* ---------------- menu ---------------- */

  function initMenu() {
    const view = document.body.dataset.view;
    if (view === "games" || view === "online") initBotSetup(view);
    if (view === "tournaments") {
      $$(".tournament-card[data-locked='1']").forEach((card) => {
        card.addEventListener("click", (event) => {
          event.preventDefault();
          showToast("Турнир ещё закрыт. Загляни позже.");
        });
      });
    }
  }

  function initBotSetup(view) {
    const cards = $$(".bot-card");
    const tcChips = $$("#tc-row .chip");
    const colorChips = $$("#color-row .chip");
    const selectedBox = $("#selected-bot");
    const startButton = $("#start-game");
    const hint = $("#start-hint");
    const state = { elo: null, name: "", fast: null, tc: null, color: "white" };

    function updateSelectedBox(card) {
      const name = card.dataset.name;
      const elo = card.dataset.elo;
      const cups = card.dataset.cups || "0";
      const avatar = card.querySelector(".bot-avatar");
      const color = avatar ? avatar.style.background : "#555";
      selectedBox.classList.add("filled");
      selectedBox.innerHTML =
        '<span class="bot-avatar" style="background:' + color + '">' + name.charAt(0) + "</span>" +
        '<span class="selected-info"><strong>' + name + "</strong>" +
        "<span>" + (elo === "1" ? "1 Эло" : elo + " Эло") + " · Кубки: " + cups + "</span></span>";
    }

    function refreshAvailability() {
      if (state.elo === null) {
        tcChips.forEach((chip) => {
          chip.classList.add("disabled");
          chip.classList.remove("active");
        });
        state.tc = null;
        updateStart();
        return;
      }
      if (view === "online") {
        let hasActive = false;
        tcChips.forEach((chip) => {
          chip.classList.remove("disabled");
          if (chip.classList.contains("active")) hasActive = true;
        });
        if (!hasActive) {
          const first = tcChips[0];
          if (first) {
            first.classList.add("active");
            state.tc = first.dataset.tc;
          }
        }
        const tcHint = $("#tc-hint");
        if (tcHint) tcHint.textContent = "Онлайн: доступен любой контроль времени.";
        updateStart();
        return;
      }
      const kind = state.fast ? "fast" : "full";
      let hasActive = false;
      tcChips.forEach((chip) => {
        const allowed = chip.dataset.kind === kind;
        chip.classList.toggle("disabled", !allowed);
        if (!allowed) chip.classList.remove("active");
        if (allowed && chip.classList.contains("active")) hasActive = true;
      });
      if (!hasActive) {
        const first = tcChips.find((chip) => chip.dataset.kind === kind);
        if (first) {
          first.classList.add("active");
          state.tc = first.dataset.tc;
        }
      }
      const tcHint = $("#tc-hint");
      if (tcHint) {
        tcHint.textContent = state.fast
          ? "Быстрая модель: 1+0, 2+1, 3+0, 3+2, 5+0. В 1+0 таймер не тикает."
          : "Уровни Stockfish: 5+3, 10+0, 10+5, 15+10, 30+0.";
      }
      updateStart();
    }

    function updateStart() {
      const ready = state.elo !== null && state.tc !== null;
      startButton.disabled = !ready;
      if (!state.elo) hint.textContent = "Выбери бота и контроль времени.";
      else if (!state.tc) hint.textContent = "Выбери контроль времени.";
      else if (view === "online") hint.textContent = "Соперник готов. Партия начнётся сразу.";
      else hint.textContent = "Партия начнётся сразу. Во время игры подсказок не будет.";
    }

    cards.forEach((card) => {
      card.addEventListener("click", () => {
        cards.forEach((item) => item.classList.toggle("selected", item === card));
        state.elo = Number(card.dataset.elo);
        state.name = card.dataset.name;
        state.fast = card.dataset.fast === "1";
        state.tc = null;
        updateSelectedBox(card);
        refreshAvailability();
      });
    });

    tcChips.forEach((chip) => {
      chip.addEventListener("click", () => {
        if (chip.classList.contains("disabled")) return;
        tcChips.forEach((item) => item.classList.toggle("active", item === chip));
        state.tc = chip.dataset.tc;
        updateStart();
      });
    });

    colorChips.forEach((chip) => {
      chip.addEventListener("click", () => {
        colorChips.forEach((item) => item.classList.toggle("active", item === chip));
        state.color = chip.dataset.color;
      });
    });

    startButton.addEventListener("click", async () => {
      if (startButton.disabled) return;
      startButton.disabled = true;
      startButton.textContent = "Запускаю...";
      const data = await api("/api/game/start", {
        method: "POST",
        body: {
          mode: view === "online" ? "online" : "games",
          bot_elo: state.elo,
          bot_name: state.name,
          time_control: state.tc,
          color: state.color
        }
      });
      if (data.ok) {
        go("/game/" + data.game_id);
      } else {
        showToast(data.error || "Не удалось начать партию");
        startButton.disabled = false;
        startButton.textContent = "Начать партию";
      }
    });

    refreshAvailability();
    updateStart();
  }

  /* ---------------- game ---------------- */

  const PIECE_FILES = { p: "P", n: "N", b: "B", r: "R", q: "Q", k: "K" };

  function pieceImage(piece) {
    const img = document.createElement("img");
    img.className = "piece " + (piece.color === "w" ? "white" : "black");
    img.src = "/static/pieces/" + piece.color + PIECE_FILES[piece.type] + ".svg";
    img.alt = "";
    img.draggable = false;
    return img;
  }
  const REASONS = {
    checkmate: "Мат",
    stalemate: "Пат",
    insufficient: "Недостаточно материала",
    fifty: "Правило 50 ходов",
    seventyfive: "Правило 75 ходов",
    repetition: "Троекратное повторение",
    fivefold: "Пятикратное повторение",
    timeout: "Просрочка времени",
    resign: "Сдача",
    agreement: "Соглашение на ничью",
    simulated: "Партия ботов"
  };

  function parseFen(fen) {
    const placement = fen.split(" ")[0];
    const rows = placement.split("/");
    const board = {};
    rows.forEach((row, rowIndex) => {
      let file = 0;
      for (const symbol of row) {
        if (symbol >= "1" && symbol <= "8") {
          file += Number(symbol);
        } else {
          const color = symbol === symbol.toUpperCase() ? "w" : "b";
          board["abcdefgh"[file] + (8 - rowIndex)] = { type: symbol.toLowerCase(), color: color };
          file += 1;
        }
      }
    });
    return board;
  }

  function capturePieceRects(boardEl) {
    return Array.from(boardEl.querySelectorAll("img.piece")).map((img) => {
      const rect = img.getBoundingClientRect();
      const cell = img.closest(".sq");
      return {
        src: img.getAttribute("src"),
        square: cell ? cell.dataset.square : "",
        left: rect.left,
        top: rect.top
      };
    });
  }

  function animatePieceRects(boardEl, previous) {
    if (!previous || !previous.length) return;
    if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const speed = (getComputedStyle(document.documentElement).getPropertyValue("--piece-speed") || "").trim() || "320ms";
    const pieces = Array.from(boardEl.querySelectorAll("img.piece"));
    const used = new Set();
    const stationary = new Set();
    const oldKeys = new Map();
    previous.forEach((item, index) => {
      oldKeys.set(item.square + "|" + item.src, index);
    });
    pieces.forEach((img) => {
      const cell = img.closest(".sq");
      const square = cell ? cell.dataset.square : "";
      const key = square + "|" + img.getAttribute("src");
      if (oldKeys.has(key)) {
        stationary.add(img);
        used.add(oldKeys.get(key));
      }
    });
    pieces.forEach((img) => {
      if (stationary.has(img)) return;
      const cell = img.closest(".sq");
      const square = cell ? cell.dataset.square : "";
      const src = img.getAttribute("src");
      const rect = img.getBoundingClientRect();
      let bestIndex = -1;
      let bestDistance = Infinity;
      previous.forEach((item, index) => {
        if (used.has(index) || item.src !== src || item.square === square) return;
        const dx = item.left - rect.left;
        const dy = item.top - rect.top;
        const distance = dx * dx + dy * dy;
        if (distance < bestDistance) {
          bestDistance = distance;
          bestIndex = index;
        }
      });
      if (bestIndex < 0) return;
      used.add(bestIndex);
      const old = previous[bestIndex];
      const dx = old.left - rect.left;
      const dy = old.top - rect.top;
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return;
      img.style.transition = "none";
      img.style.transform = "translate(" + dx + "px, " + dy + "px)";
      requestAnimationFrame(() => {
        img.style.transition = "transform " + speed + " cubic-bezier(0.22, 0.75, 0.2, 1)";
        img.style.transform = "translate(0, 0)";
      });
      const clear = () => {
        img.style.transition = "";
        img.style.transform = "";
      };
      img.addEventListener("transitionend", clear, { once: true });
      setTimeout(clear, (parseInt(speed, 10) || 320) + 200);
    });
  }

  function formatClock(ms) {
    if (ms === null || ms === undefined) return "--:--";
    const total = Math.max(0, Math.ceil(ms / 1000));
    const minutes = Math.floor(total / 60);
    const seconds = total % 60;
    return minutes + ":" + String(seconds).padStart(2, "0");
  }

  function initGame() {
    const gameId = Number(document.body.dataset.gameId);
    const boardEl = $("#board");
    const statusEl = $("#status-line");
    const moveList = $("#move-list");
    const clockTop = $("#clock-top");
    const clockBottom = $("#clock-bottom");
    const resultModal = $("#result-modal");
    const resignBtn = $("#resign-btn");
    const drawBtn = $("#draw-btn");
    const rematchBtn = $("#rematch-btn");
    const analysisLink = $("#analysis-link");
    const promotionModal = $("#promotion-modal");
    const state = {
      data: null,
      selected: null,
      orientation: null,
      clockSync: null,
      finishedShown: false,
      pendingPromotion: null,
      timeoutRequested: false,
      renderSignature: "",
      boardSignature: ""
    };

    function userColor() {
      return state.data ? state.data.user_color : "white";
    }

    function isUserTurn() {
      return state.data && state.data.status === "active" && state.data.turn === userColor();
    }

    function render() {
      if (!state.data) return;
      const lastMove = state.data.last_move;
      const boardSignature = [
        state.data.fen,
        state.orientation,
        lastMove ? lastMove.from + lastMove.to : "",
        state.data.check ? "1" : "0",
        state.data.thinking ? "1" : "0",
        state.data.status || "",
        (state.data.legal || []).length
      ].join("|");
      const signature = boardSignature + "|" + (state.selected || "") + "|" + (state.cursor || "");
      if (signature === state.renderSignature) return;
      const sameBoard = boardSignature === state.boardSignature;
      state.renderSignature = signature;
      state.boardSignature = boardSignature;
      if (sameBoard && boardEl.childElementCount === 64) {
        const pieces = parseFen(state.data.fen);
        const legalMap = {};
        (state.data.legal || []).forEach((uci) => {
          const from = uci.slice(0, 2);
          if (!legalMap[from]) legalMap[from] = [];
          legalMap[from].push({ to: uci.slice(2, 4), uci: uci });
        });
        const targets = state.selected ? legalMap[state.selected] || [] : [];
        const bySquare = {};
        targets.forEach((target) => {
          bySquare[target.to] = target.uci;
        });
        Array.from(boardEl.querySelectorAll(".sq")).forEach((cell) => {
          const square = cell.dataset.square;
          const isLegal = Object.prototype.hasOwnProperty.call(bySquare, square);
          const uci = bySquare[square] || "";
          cell.classList.toggle("selected", square === state.selected);
          cell.classList.toggle("cursor", square === state.cursor);
          cell.classList.toggle("legal", isLegal);
          cell.classList.toggle("capture", isLegal && (!!pieces[square] || uci.length > 4));
        });
        updateStatus();
        return;
      }
      const previousPieces = capturePieceRects(boardEl);
      const board = parseFen(state.data.fen);
      const flipped = state.orientation === "black";
      const files = flipped ? "hgfedcba" : "abcdefgh";
      const ranks = flipped ? [1, 2, 3, 4, 5, 6, 7, 8] : [8, 7, 6, 5, 4, 3, 2, 1];
      const legalTargets = {};
      const legalList = state.data.legal || [];
      legalList.forEach((uci) => {
        const from = uci.slice(0, 2);
        const to = uci.slice(2, 4);
        if (!legalTargets[from]) legalTargets[from] = [];
        legalTargets[from].push({ to: to, uci: uci });
      });
      state.legalTargets = legalTargets;
      const last = state.data.last_move;
      const checkSquare = state.data.check ? findKing(board, state.data.turn) : null;
      boardEl.innerHTML = "";
      ranks.forEach((rank, rankIndex) => {
        Array.from(files).forEach((file, fileIndex) => {
          const square = file + rank;
          const cell = document.createElement("div");
          const isLight = (file.charCodeAt(0) - 97 + rank) % 2 === 0;
          cell.className = "sq " + (isLight ? "light" : "dark");
          cell.dataset.square = square;
          if (last && (last.from === square || last.to === square)) cell.classList.add("last");
          if (state.cursor === square) cell.classList.add("cursor");
          cell.setAttribute("role", "gridcell");
          cell.setAttribute("aria-label", square);
          if (state.selected === square) cell.classList.add("selected");
          if (checkSquare === square) cell.classList.add("check");
          const piece = board[square];
          if (piece) cell.appendChild(pieceImage(piece));
          if (state.selected && legalTargets[state.selected]) {
            const target = legalTargets[state.selected].find((item) => item.to === square);
            if (target) {
              cell.classList.add("legal");
              if (piece || (target.uci.length > 4)) cell.classList.add("capture");
            }
          }
          if (rankIndex === 7) {
            const coord = document.createElement("span");
            coord.className = "coord file";
            coord.textContent = file;
            cell.appendChild(coord);
          }
          if (fileIndex === 0) {
            const coord = document.createElement("span");
            coord.className = "coord rank";
            coord.textContent = rank;
            cell.appendChild(coord);
          }
          cell.addEventListener("click", () => onSquareClick(square, board[square], legalTargets));
          boardEl.appendChild(cell);
        });
      });
      animatePieceRects(boardEl, previousPieces);
      updateStatus();
      renderMoveList();
    }

    function findKing(board, color) {
      const target = color === "white" ? "w" : "b";
      for (const square in board) {
        if (board[square].type === "k" && board[square].color === target) return square;
      }
      return null;
    }

    function setPromotionColor(color) {
      promotionModal.querySelectorAll(".promotion-btn").forEach((button) => {
        const img = button.querySelector("img");
        if (!img) return;
        const type = (button.dataset.piece || "q").toUpperCase();
        img.src = "/static/pieces/" + (color === "black" ? "b" : "w") + type + ".svg";
      });
    }

    function onSquareClick(square, piece, legalTargets) {
      if (!state.data || state.data.status !== "active") return;
      if (!isUserTurn()) {
        showToast("Сейчас ход соперника");
        return;
      }
      if (state.selected) {
        const moves = (legalTargets[state.selected] || []).filter((item) => item.to === square);
        if (moves.length > 0) {
          if (moves.length > 1) {
            state.pendingPromotion = { from: state.selected, to: square };
            setPromotionColor(userColor());
            promotionModal.classList.remove("hidden");
          } else {
            sendMove(state.selected, square, moves[0].uci.length > 4 ? moves[0].uci.slice(4) : null);
          }
          return;
        }
      }
      if (piece && ((piece.color === "w" && userColor() === "white") || (piece.color === "b" && userColor() === "black"))) {
        state.selected = square;
      } else {
        state.selected = null;
      }
      render();
    }

    async function sendMove(from, to, promotion) {
      if (!state.data || state.data.status !== "active") return;
      state.selected = null;
      boardEl.classList.add("locked");
      statusEl.textContent = "Соперник думает...";
      const data = await api("/api/game/move", {
        method: "POST",
        body: { game_id: gameId, from: from, to: to, promotion: promotion || null }
      });
      boardEl.classList.remove("locked");
      if (!data.ok) {
        showToast(data.error || "Ход не принят");
        render();
        return;
      }
      applyState(data.state);
    }

    function updateStatus() {
      if (!state.data) return;
      if (state.data.status === "finished") {
        const result = state.data.result;
        const title = result === "win" ? "Победа" : result === "loss" ? "Поражение" : "Ничья";
        statusEl.textContent = title + " · " + (REASONS[state.data.reason] || "партия завершена");
        return;
      }
      if (state.data.turn === userColor()) {
        statusEl.textContent = state.data.check ? "Твой ход. Шах!" : "Твой ход";
      } else if (state.data.thinking) {
        statusEl.textContent = "Соперник думает...";
      } else {
        statusEl.textContent = "Ход соперника";
      }
    }

    function renderMoveList() {
      if (!state.data) return;
      const moves = state.data.moves || [];
      moveList.innerHTML = "";
      if (moves.length === 0) {
        const empty = document.createElement("div");
        empty.className = "empty-moves";
        empty.textContent = "Ходов пока нет.";
        moveList.appendChild(empty);
        return;
      }
      for (let index = 0; index < moves.length; index += 2) {
        const line = document.createElement("div");
        line.className = "move-line";
        const no = document.createElement("span");
        no.className = "move-no";
        no.textContent = String(index / 2 + 1) + ".";
        line.appendChild(no);
        for (let offset = 0; offset < 2; offset += 1) {
          const move = moves[index + offset];
          const cell = document.createElement("span");
          cell.className = "move-san";
          cell.textContent = move ? move.san : "";
          line.appendChild(cell);
        }
        moveList.appendChild(line);
      }
      moveList.scrollTop = moveList.scrollHeight;
    }

    function syncClocks() {
      if (!state.data) return;
      state.clockSync = {
        white: state.data.clocks.white_ms,
        black: state.data.clocks.black_ms,
        active: state.data.clocks.active,
        at: performance.now()
      };
    }

    function tickClocks() {
      if (!state.data) return;
      const timed = state.data.timed;
      const topColor = userColor() === "white" ? "black" : "white";
      const bottomColor = userColor();
      if (!timed) {
        const label = state.data.time_control === "1+0" ? "1:00" : "∞";
        clockTop.textContent = label;
        clockBottom.textContent = label;
        clockTop.classList.remove("low", "active");
        clockBottom.classList.remove("low", "active");
        return;
      }
      if (!state.clockSync) return;
      let white = state.clockSync.white;
      let black = state.clockSync.black;
      if (state.data.status === "active") {
        const elapsed = performance.now() - state.clockSync.at;
        if (state.clockSync.active === "white") white -= elapsed;
        else black -= elapsed;
      }
      const topMs = topColor === "white" ? white : black;
      const bottomMs = bottomColor === "white" ? white : black;
      clockTop.textContent = formatClock(topMs);
      clockBottom.textContent = formatClock(bottomMs);
      clockTop.classList.toggle("low", topMs <= 20000);
      clockBottom.classList.toggle("low", bottomMs <= 20000);
      clockTop.classList.toggle("active", state.data.status === "active" && state.clockSync.active === topColor);
      clockBottom.classList.toggle("active", state.data.status === "active" && state.clockSync.active === bottomColor);
      if (white <= 0 || black <= 0) {
        if (!state.timeoutRequested) {
          state.timeoutRequested = true;
          refreshState();
        }
      }
    }

    function updateClockNote(data) {
      const note = $("#clock-note");
      if (!note) return;
      if (!data) {
        note.textContent = "";
        return;
      }
      const tc = data.time_control || "";
      if (tc === "1+0") {
        note.textContent = "1+0: бесконечное раздумье — таймер не тикает.";
        return;
      }
      const parts = tc.split("+");
      if (parts.length === 2 && parts[0] !== "" && parts[1] !== "") {
        note.textContent = tc + ": " + parts[0] + " мин + " + parts[1] + " сек за ход.";
      } else {
        note.textContent = "";
      }
    }

    let botPoll = null;

    function startBotPolling() {
      if (botPoll) return;
      botPoll = setInterval(async () => {
        if (!state.data) return;
        if (!state.data.thinking) {
          stopBotPolling();
          return;
        }
        await refreshState();
      }, 450);
    }

    function stopBotPolling() {
      if (!botPoll) return;
      clearInterval(botPoll);
      botPoll = null;
    }

    function applyState(next) {
      const previous = state.data;
      state.data = next;
      state.selected = null;
      state.finishedShown = false;
      if (!state.orientation) state.orientation = next.user_color === "black" ? "black" : "white";
      if (!state.cursor) state.cursor = next.user_color === "black" ? "e7" : "e2";
      if (previous) {
        const prevMoves = previous.moves ? previous.moves.length : 0;
        const nextMoves = next.moves ? next.moves.length : 0;
        if (nextMoves > prevMoves) {
          const last = next.moves[nextMoves - 1];
          const isCapture = last && last.san && last.san.indexOf("x") !== -1;
          playSound(next.check ? "check" : (isCapture ? "capture" : "move"));
        }
        if (next.status === "finished" && previous.status !== "finished") playSound("end");
      }
      const oppName = next.bot ? next.bot.name : "Соперник";
      $("#opp-name").textContent = oppName;
      $("#opp-elo").textContent = (next.bot ? next.bot.elo : "") + " Эло";
      const oppAvatar = $("#opp-avatar");
      if (oppAvatar) oppAvatar.textContent = oppName.charAt(0);
      $("#my-elo").textContent = next.mode === "games" ? "Эло не меняется" : $("#my-elo").textContent;
      const waiting = next.status === "active" && !!next.thinking;
      boardEl.classList.toggle("locked", waiting);
      if (waiting) startBotPolling();
      else stopBotPolling();
      syncClocks();
      updateClockNote(next);
      render();
      if (next.status === "finished") showResult();
    }

    function showResult() {
      if (!state.data || state.data.status !== "finished" || state.finishedShown) return;
      state.finishedShown = true;
      const result = state.data.result;
      const title = result === "win" ? "Победа" : result === "loss" ? "Поражение" : "Ничья";
      $("#result-title").textContent = title;
      $("#result-reason").textContent = REASONS[state.data.reason] || "Партия завершена";
      $("#result-icon").textContent = result === "win" ? "♛" : result === "loss" ? "♚" : "½";
      $("#result-score").textContent = state.data.moves.length + " ходов";
      analysisLink.href = "/analysis/" + gameId;
      resultModal.classList.remove("hidden");
      resignBtn.disabled = true;
      drawBtn.disabled = true;
    }

    async function refreshState() {
      const data = await api("/api/game/" + gameId + "/state");
      if (!data.ok) {
        showToast(data.error || "Не удалось загрузить партию");
        return;
      }
      applyState(data.state);
    }

    promotionModal.querySelectorAll(".promotion-btn").forEach((button) => {
      button.addEventListener("click", () => {
        const pending = state.pendingPromotion;
        promotionModal.classList.add("hidden");
        if (!pending) return;
        state.pendingPromotion = null;
        sendMove(pending.from, pending.to, button.dataset.piece);
      });
    });

    resignBtn.addEventListener("click", async () => {
      if (!state.data || state.data.status !== "active") return;
      if (!window.confirm("Точно сдать партию?")) return;
      resignBtn.disabled = true;
      const data = await api("/api/game/resign", {
        method: "POST",
        body: { game_id: gameId }
      });
      if (data.ok) applyState(data.state);
      else {
        resignBtn.disabled = false;
        showToast(data.error || "Не получилось сдать партию");
      }
    });

    drawBtn.addEventListener("click", async () => {
      if (!state.data || state.data.status !== "active") return;
      drawBtn.disabled = true;
      const data = await api("/api/game/draw", {
        method: "POST",
        body: { game_id: gameId }
      });
      if (data.ok) {
        applyState(data.state);
        if (!data.accepted) {
          showToast("Соперник отказался от ничьей");
          drawBtn.disabled = false;
        }
      } else {
        drawBtn.disabled = false;
        showToast(data.error || "Не получилось предложить ничью");
      }
    });

    rematchBtn.addEventListener("click", async () => {
      rematchBtn.disabled = true;
      const data = await api("/api/game/rematch", {
        method: "POST",
        body: { game_id: gameId }
      });
      if (data.ok) go("/game/" + data.game_id);
      else {
        rematchBtn.disabled = false;
        showToast(data.error || "Реванш недоступен");
      }
    });

    boardEl.addEventListener("keydown", (event) => {
      if (!state.data) return;
      const keys = ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Enter", " ", "Escape"];
      if (keys.indexOf(event.key) === -1) return;
      event.preventDefault();
      if (event.key === "Escape") {
        state.selected = null;
        render();
        return;
      }
      if (event.key === "Enter" || event.key === " ") {
        const square = state.cursor;
        if (!square) return;
        const pieces = parseFen(state.data.fen);
        onSquareClick(square, pieces[square], state.legalTargets || {});
        return;
      }
      const flipped = state.orientation === "black";
      const files = "abcdefgh";
      let file = files.indexOf((state.cursor || "e2")[0]);
      let rank = Number((state.cursor || "e2")[1]) || 2;
      if (file < 0) file = 4;
      const up = flipped ? -1 : 1;
      const right = flipped ? -1 : 1;
      if (event.key === "ArrowUp") rank += up;
      if (event.key === "ArrowDown") rank -= up;
      if (event.key === "ArrowRight") file += right;
      if (event.key === "ArrowLeft") file -= right;
      file = Math.max(0, Math.min(7, file));
      rank = Math.max(1, Math.min(8, rank));
      state.cursor = files[file] + rank;
      render();
    });

    refreshState();
    setInterval(tickClocks, 200);
  }

  /* ---------------- tournament ---------------- */

  function initTournament() {
    const startButton = $("#start-tournament");
    if (startButton) {
      startButton.addEventListener("click", async () => {
        const num = startButton.dataset.num;
        startButton.disabled = true;
        startButton.textContent = "Открываю сетку...";
        const data = await api("/api/tournament/" + num + "/start", { method: "POST" });
        if (data.ok) window.location.reload();
        else {
          showToast(data.error || "Не удалось начать турнир");
          startButton.disabled = false;
          startButton.textContent = "Начать турнир";
        }
      });
    }
    const playButton = $("#play-round");
    if (playButton) {
      playButton.addEventListener("click", async () => {
        const num = playButton.dataset.num;
        playButton.disabled = true;
        playButton.textContent = "Готовлю партию...";
        const data = await api("/api/tournament/" + num + "/play", { method: "POST" });
        if (data.ok) go("/game/" + data.game_id);
        else {
          showToast(data.error || "Не удалось начать раунд");
          playButton.disabled = false;
          playButton.textContent = "Играть раунд";
        }
      });
    }
  }

  /* ---------------- backups ---------------- */

  function initBackups() {
    const create = $("#backup-create");
    if (create) {
      create.addEventListener("click", async () => {
        create.disabled = true;
        create.textContent = "Создаю копию...";
        const data = await api("/api/backups/create", { method: "POST" });
        if (data.ok) {
          showToast("Копия создана");
          setTimeout(() => window.location.reload(), 700);
        } else {
          create.disabled = false;
          create.textContent = "Создать копию сейчас";
          showToast(data.error || "Не удалось создать копию");
        }
      });
    }

    $$(".backup-restore").forEach((button) => {
      button.addEventListener("click", async () => {
        const name = button.dataset.name || "";
        const stamp = name.replace("database-", "").replace(".db", "");
        if (!window.confirm("Заменить текущую базу копией " + stamp + "?")) return;
        button.disabled = true;
        const data = await api("/api/backups/restore", {
          method: "POST",
          body: { name: name }
        });
        if (data.ok) {
          if (data.redirect) {
            go(data.redirect);
            return;
          }
          showToast("База восстановлена");
          setTimeout(() => window.location.reload(), 700);
        } else {
          button.disabled = false;
          showToast(data.error || "Не удалось восстановить копию");
        }
      });
    });
  }

  /* ---------------- profile ---------------- */

  function initProfile() {
    const changeForm = $("#change-password-form");
    if (changeForm) {
      changeForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const data = await api("/api/password/change", {
          method: "POST",
          body: {
            current_password: $("#current-password").value,
            new_password: $("#new-password").value
          }
        });
        if (data.ok) {
          changeForm.reset();
          showToast("Пароль обновлён");
        } else {
          showToast(data.error || "Не удалось сменить пароль");
        }
      });
    }

    const generate = $("#generate-recovery");
    if (generate) {
      generate.addEventListener("click", async () => {
        generate.disabled = true;
        const data = await api("/api/recovery/code", { method: "POST" });
        generate.disabled = false;
        const box = $("#profile-recovery");
        if (data.ok) {
          if (box) box.textContent = data.recovery_code;
          showToast("Новый код готов — сохрани его");
        } else {
          showToast(data.error || "Не удалось создать код");
        }
      });
    }

    const delaySelect = $("#bot-delay");
    const saveDelay = $("#save-delay");
    if (delaySelect && saveDelay) {
      (async () => {
        const data = await api("/api/settings");
        if (data.ok && data.settings) {
          const value = String(Math.round(Number(data.settings.bot_delay) || 3));
          delaySelect.value = value;
        }
      })();
      saveDelay.addEventListener("click", async () => {
        saveDelay.disabled = true;
        const data = await api("/api/settings", {
          method: "POST",
          body: { bot_delay: Number(delaySelect.value) }
        });
        saveDelay.disabled = false;
        if (data.ok) showToast("Задержка: " + data.settings.bot_delay + " с");
        else showToast(data.error || "Не удалось сохранить задержку");
      });
    }

    const themeSelect = $("#ui-theme");
    const soundBox = $("#ui-sound");
    const coordsBox = $("#ui-coords");
    const speedRange = $("#piece-speed");
    const speedValue = $("#piece-speed-value");
    const saveUi = $("#save-ui");
    if (themeSelect && saveUi) {
      (async () => {
        const data = await api("/api/settings");
        if (!data.ok || !data.settings) return;
        themeSelect.value = data.settings.theme === "dark" ? "dark" : "light";
        soundBox.checked = !!data.settings.sound;
        coordsBox.checked = !!data.settings.coordinates;
        if (speedRange) {
          speedRange.value = data.settings.piece_speed;
          if (speedValue) speedValue.textContent = data.settings.piece_speed;
        }
      })();
      if (speedRange) {
        speedRange.addEventListener("input", () => {
          const value = Number(speedRange.value) || 320;
          document.documentElement.style.setProperty("--piece-speed", value + "ms");
          if (speedValue) speedValue.textContent = value;
        });
      }
      saveUi.addEventListener("click", async () => {
        saveUi.disabled = true;
        const data = await api("/api/settings", {
          method: "POST",
          body: {
            theme: themeSelect.value,
            sound: soundBox.checked,
            coordinates: coordsBox.checked,
            piece_speed: speedRange ? Number(speedRange.value) : 320
          }
        });
        saveUi.disabled = false;
        if (data.ok) {
          const root = document.documentElement;
          root.dataset.theme = data.settings.theme;
          root.dataset.sound = data.settings.sound ? "on" : "off";
          root.dataset.coords = data.settings.coordinates ? "on" : "off";
          root.style.setProperty("--piece-speed", data.settings.piece_speed + "ms");
          if (speedValue) speedValue.textContent = data.settings.piece_speed;
          showToast("Оформление сохранено");
        } else {
          showToast(data.error || "Не удалось сохранить оформление");
        }
      });
    }

    const BOARD_PRESETS = {
      green: ["#eeeed2", "#769656"],
      brown: ["#f0d9b5", "#b58863"],
      blue: ["#dee3e6", "#8ca2ad"],
      gray: ["#e9e6e1", "#9a9a90"],
      purple: ["#e8e1f0", "#8a72ab"],
      wood: ["#e8d3b0", "#a07d52"],
      dark: ["#8a8a80", "#4a4a44"]
    };
    const BOARD_NAMES = {
      green: "Зелёная",
      brown: "Коричневая",
      blue: "Голубая",
      gray: "Серая",
      purple: "Фиолетовая",
      wood: "Дерево",
      dark: "Тёмная"
    };
    const themesBox = $("#board-themes");
    const lightInput = $("#board-light");
    const darkInput = $("#board-dark");
    const saveBoard = $("#save-board");

    function applyBoard(theme, light, dark) {
      const root = document.documentElement;
      root.dataset.board = theme;
      root.style.setProperty("--board-light", light);
      root.style.setProperty("--board-dark", dark);
    }

    function markActiveBoard(theme) {
      if (!themesBox) return;
      Array.from(themesBox.children).forEach((el) => {
        el.classList.toggle("active", el.dataset.board === theme);
      });
    }

    function buildBoardThemes() {
      if (!themesBox) return;
      themesBox.innerHTML = "";
      Object.keys(BOARD_PRESETS).forEach((key) => {
        const colors = BOARD_PRESETS[key];
        const button = document.createElement("button");
        button.type = "button";
        button.className = "board-theme";
        button.dataset.board = key;
        button.title = BOARD_NAMES[key] || key;
        button.style.setProperty("--sw-light", colors[0]);
        button.style.setProperty("--sw-dark", colors[1]);
        for (let index = 0; index < 4; index += 1) {
          button.appendChild(document.createElement("span"));
        }
        button.addEventListener("click", async () => {
          applyBoard(key, colors[0], colors[1]);
          if (lightInput) lightInput.value = colors[0];
          if (darkInput) darkInput.value = colors[1];
          markActiveBoard(key);
          const data = await api("/api/settings", {
            method: "POST",
            body: { board_theme: key }
          });
          if (!data.ok) showToast(data.error || "Не удалось сохранить тему");
        });
        themesBox.appendChild(button);
      });
    }

    if (themesBox) {
      buildBoardThemes();
      (async () => {
        const data = await api("/api/settings");
        if (!data.ok || !data.settings) return;
        if (lightInput) lightInput.value = data.settings.board_light;
        if (darkInput) darkInput.value = data.settings.board_dark;
        markActiveBoard(data.settings.board_theme);
      })();

      [lightInput, darkInput].forEach((input) => {
        if (!input) return;
        input.addEventListener("input", () => {
          applyBoard("custom", lightInput.value, darkInput.value);
          markActiveBoard("");
        });
      });

      if (saveBoard) {
        saveBoard.addEventListener("click", async () => {
          saveBoard.disabled = true;
          const data = await api("/api/settings", {
            method: "POST",
            body: {
              board_theme: "custom",
              board_light: lightInput.value,
              board_dark: darkInput.value
            }
          });
          saveBoard.disabled = false;
          if (data.ok) {
            applyBoard("custom", data.settings.board_light, data.settings.board_dark);
            markActiveBoard("");
            showToast("Тема доски сохранена");
          } else {
            showToast(data.error || "Не удалось сохранить тему");
          }
        });
      }
    }

    const importFile = $("#profile-import-file");
    if (importFile) {
      importFile.addEventListener("change", async () => {
        const file = importFile.files && importFile.files[0];
        if (!file) return;
        let payload = null;
        try {
          payload = JSON.parse(await file.text());
        } catch (error) {
          showToast("Файл не читается: нужен JSON из экспорта");
          importFile.value = "";
          return;
        }
        const data = await api("/api/account/import", {
          method: "POST",
          body: { payload: payload }
        });
        importFile.value = "";
        if (data.ok) {
          showToast("Добавлено партий: " + data.imported.games);
          setTimeout(() => window.location.reload(), 900);
        } else {
          showToast(data.error || "Не удалось загрузить файл");
        }
      });
    }
  }

  /* ---------------- import / editor ---------------- */

  const IMPORT_START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
  const FEN_LETTERS = { p: "p", n: "n", b: "b", r: "r", q: "q", k: "k" };

  function initImport() {
    const boardEl = $("#edit-board");
    const paletteEl = $("#edit-palette");
    const fenInput = $("#fen-input");
    const turnSelect = $("#edit-turn");
    const statusEl = $("#edit-status");
    const fenStatus = $("#fen-status");
    const state = {
      fen: IMPORT_START_FEN,
      turn: "white",
      picked: null,
      brush: null
    };

    function fenLetter(piece) {
      const letter = FEN_LETTERS[piece.type.toLowerCase()];
      return piece.color === "w" ? letter.toUpperCase() : letter;
    }

    function buildFen(pieces, turn) {
      const rows = [];
      for (let rank = 8; rank >= 1; rank -= 1) {
        let row = "";
        let empty = 0;
        "abcdefgh".split("").forEach((file) => {
          const piece = pieces[file + rank];
          if (!piece) {
            empty += 1;
            return;
          }
          if (empty) {
            row += String(empty);
            empty = 0;
          }
          row += fenLetter(piece);
        });
        if (empty) row += String(empty);
        rows.push(row);
      }
      let rights = "";
      const wK = pieces.e1;
      if (wK && wK.type === "k" && wK.color === "w") {
        if (pieces.h1 && pieces.h1.type === "r" && pieces.h1.color === "w") rights += "K";
        if (pieces.a1 && pieces.a1.type === "r" && pieces.a1.color === "w") rights += "Q";
      }
      const bK = pieces.e8;
      if (bK && bK.type === "k" && bK.color === "b") {
        if (pieces.h8 && pieces.h8.type === "r" && pieces.h8.color === "b") rights += "k";
        if (pieces.a8 && pieces.a8.type === "r" && pieces.a8.color === "b") rights += "q";
      }
      const side = turn === "black" ? "b" : "w";
      return rows.join("/") + " " + side + " " + (rights || "-") + " - 0 1";
    }

    function onCell(square) {
      const pieces = parseFen(state.fen);
      if (state.brush === "erase") {
        if (pieces[square]) {
          delete pieces[square];
          state.fen = buildFen(pieces, state.turn);
        }
        render();
        return;
      }
      if (state.brush && state.brush.fromPalette) {
        pieces[square] = { type: state.brush.type, color: state.brush.color };
        state.fen = buildFen(pieces, state.turn);
        render();
        return;
      }
      if (state.picked) {
        if (state.picked !== square && pieces[state.picked]) {
          const moving = pieces[state.picked];
          delete pieces[state.picked];
          pieces[square] = moving;
          state.fen = buildFen(pieces, state.turn);
        }
        state.picked = null;
        render();
        return;
      }
      if (pieces[square]) {
        state.picked = square;
        render();
      }
    }

    function render() {
      const pieces = parseFen(state.fen);
      boardEl.innerHTML = "";
      for (let rank = 8; rank >= 1; rank -= 1) {
        "abcdefgh".split("").forEach((file) => {
          const square = file + rank;
          const cell = document.createElement("div");
          const isLight = (file.charCodeAt(0) - 97 + rank) % 2 === 0;
          cell.className = "sq " + (isLight ? "light" : "dark");
          cell.dataset.square = square;
          if (state.picked === square) cell.classList.add("selected");
          const piece = pieces[square];
          if (piece) cell.appendChild(pieceImage(piece));
          cell.addEventListener("click", () => onCell(square));
          boardEl.appendChild(cell);
        });
      }
      fenInput.value = state.fen;
      turnSelect.value = state.turn;
      const parts = state.fen.split(" ");
      const rights = parts[2] && parts[2] !== "-" ? "рокировки " + parts[2] : "без рокировок";
      statusEl.textContent = "Ход " + (state.turn === "black" ? "чёрных" : "белых") + " · " + rights;
    }

    function buildPalette() {
      paletteEl.innerHTML = "";
      const order = ["k", "q", "r", "b", "n", "p"];
      ["w", "b"].forEach((color) => {
        order.forEach((type) => {
          const button = document.createElement("button");
          button.type = "button";
          button.className = "palette-btn";
          button.dataset.piece = color + type;
          button.appendChild(pieceImage({ type: type, color: color }));
          button.addEventListener("click", () => {
            state.picked = null;
            state.brush = { type: type, color: color, fromPalette: true };
            Array.from(paletteEl.children).forEach((el) => el.classList.remove("active"));
            button.classList.add("active");
            render();
          });
          paletteEl.appendChild(button);
        });
      });
      const eraser = document.createElement("button");
      eraser.type = "button";
      eraser.className = "palette-btn eraser";
      eraser.textContent = "✕";
      eraser.title = "Убрать фигуру";
      eraser.addEventListener("click", () => {
        state.picked = null;
        state.brush = "erase";
        Array.from(paletteEl.children).forEach((el) => el.classList.remove("active"));
        eraser.classList.add("active");
        render();
      });
      paletteEl.appendChild(eraser);
    }

    turnSelect.addEventListener("change", () => {
      state.turn = turnSelect.value === "black" ? "black" : "white";
      state.fen = buildFen(parseFen(state.fen), state.turn);
      render();
    });

    $("#edit-start").addEventListener("click", () => {
      state.fen = IMPORT_START_FEN;
      state.turn = "white";
      state.picked = null;
      render();
    });

    $("#edit-clear").addEventListener("click", () => {
      state.fen = buildFen({}, state.turn);
      state.picked = null;
      render();
    });

    $("#edit-copy").addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(state.fen);
        showToast("FEN скопирован");
      } catch (error) {
        showToast("Скопируй FEN вручную");
      }
    });

    $("#fen-load").addEventListener("click", async () => {
      fenStatus.textContent = "";
      const data = await api("/api/position/validate", {
        method: "POST",
        body: { fen: fenInput.value }
      });
      if (!data.ok) {
        fenStatus.textContent = data.error || "FEN не подошёл";
        return;
      }
      state.fen = data.fen;
      state.turn = data.turn === "black" ? "black" : "white";
      state.picked = null;
      render();
      fenStatus.textContent = data.over ? "Позиция уже завершена — играть нельзя." : "Позиция загружена.";
    });

    $("#fen-play").addEventListener("click", async () => {
      fenStatus.textContent = "";
      const botElo = Number($("#fen-bot").value) || 1;
      const tc = botElo === 1 ? "1+0" : $("#fen-tc").value;
      const data = await api("/api/game/start", {
        method: "POST",
        body: { mode: "games", bot_elo: botElo, time_control: tc, fen: state.fen }
      });
      if (data.ok) {
        go("/game/" + data.game_id);
        return;
      }
      fenStatus.textContent = data.error || "Не удалось начать партию";
    });

    $("#pgn-import").addEventListener("click", async () => {
      const status = $("#pgn-status");
      status.textContent = "";
      const text = $("#pgn-text").value;
      if (!text.trim()) {
        status.textContent = "Вставь PGN или загрузи файл";
        return;
      }
      const data = await api("/api/import/pgn", { method: "POST", body: { pgn: text } });
      if (data.ok) {
        status.textContent = "Готово, открываю разбор...";
        go(data.redirect || "/analysis/" + data.game_id);
        return;
      }
      status.textContent = data.error || "Не удалось импортировать";
    });

    const fileInput = $("#pgn-file");
    fileInput.addEventListener("change", async () => {
      const file = fileInput.files && fileInput.files[0];
      if (!file) return;
      const text = await file.text();
      $("#pgn-text").value = text;
      fileInput.value = "";
    });

    buildPalette();
    render();
  }

  /* ---------------- training ---------------- */

  const TRAINING_NAMES = {
    brilliant: "Блестящий",
    amethyst: "Аметистовый",
    ideal: "Идеальный"
  };

  function initTraining() {
    const boardEl = $("#train-board");
    const counter = $("#train-counter");
    const labelEl = $("#train-label");
    const feedback = $("#train-feedback");
    const hint = $("#train-hint");
    const analysisLink = $("#train-analysis");
    const state = {
      list: [],
      index: -1,
      orientation: "white",
      selected: null,
      done: false,
      revealed: []
    };

    function current() {
      return state.list[state.index] || null;
    }

    function fenTurn(fen) {
      return fen.split(" ")[1] === "b" ? "black" : "white";
    }

    function render() {
      const position = current();
      if (!position) {
        boardEl.innerHTML = "";
        return;
      }
      const pieces = parseFen(position.fen);
      const flipped = state.orientation === "black";
      const files = (flipped ? "hgfedcba" : "abcdefgh").split("");
      const ranks = flipped ? [1, 2, 3, 4, 5, 6, 7, 8] : [8, 7, 6, 5, 4, 3, 2, 1];
      boardEl.innerHTML = "";
      ranks.forEach((rank) => {
        files.forEach((file) => {
          const square = file + rank;
          const cell = document.createElement("div");
          const isLight = (file.charCodeAt(0) - 97 + rank) % 2 === 0;
          cell.className = "sq " + (isLight ? "light" : "dark");
          cell.dataset.square = square;
          if (state.selected === square) cell.classList.add("selected");
          if (state.revealed.indexOf(square) !== -1) cell.classList.add("last");
          const piece = pieces[square];
          if (piece) cell.appendChild(pieceImage(piece));
          cell.addEventListener("click", () => onCell(square));
          boardEl.appendChild(cell);
        });
      });
    }

    function labelText(position) {
      return TRAINING_NAMES[position.label] || position.label;
    }

    function onCell(square) {
      const position = current();
      if (!position || state.done) return;
      const pieces = parseFen(position.fen);
      if (!state.selected) {
        const piece = pieces[square];
        if (!piece) return;
        const side = fenTurn(position.fen) === "white" ? "w" : "b";
        if (piece.color !== side) return;
        state.selected = square;
        render();
        return;
      }
      if (state.selected === square) {
        state.selected = null;
        render();
        return;
      }
      const guess = state.selected + square;
      state.selected = null;
      if (guess === position.uci || guess + "q" === position.uci || guess + "n" === position.uci) {
        state.done = true;
        state.revealed = [position.from, position.to];
        feedback.textContent = "Верно! " + position.san + " — " + labelText(position).toLowerCase() + " ход.";
        render();
        return;
      }
      feedback.textContent = "Не то. Попробуй ещё раз или открой ответ.";
      render();
    }

    function setPosition() {
      const position = current();
      state.selected = null;
      state.revealed = [];
      state.done = false;
      if (!position) {
        boardEl.innerHTML = "";
        counter.textContent = "Готово";
        labelEl.textContent = "—";
        analysisLink.classList.add("hidden");
        hint.textContent = "";
        feedback.textContent = state.list.length
          ? "Позиции закончились. Обнови страницу, чтобы пройти заново."
          : "Пока нет подходящих позиций. Сыграй партию, открой разбор — и блестящие ходы появятся здесь.";
        return;
      }
      state.orientation = fenTurn(position.fen);
      counter.textContent = state.index + 1 + " / " + state.list.length;
      labelEl.textContent = labelText(position);
      feedback.textContent = "Твой ход. Найди сильнейшее продолжение.";
      hint.textContent = "Партия №" + position.game_id + " · ход " + Math.floor(position.ply / 2 + 1);
      analysisLink.href = "/analysis/" + position.game_id;
      analysisLink.classList.remove("hidden");
      render();
    }

    $("#train-flip").addEventListener("click", () => {
      state.orientation = state.orientation === "white" ? "black" : "white";
      render();
    });

    $("#train-reveal").addEventListener("click", () => {
      const position = current();
      if (!position || state.done) return;
      state.done = true;
      state.selected = null;
      state.revealed = [position.from, position.to];
      feedback.textContent = "Ответ: " + position.san + " — " + labelText(position).toLowerCase() + " ход.";
      render();
    });

    $("#train-next").addEventListener("click", () => {
      if (state.index + 1 < state.list.length) {
        state.index += 1;
      } else {
        state.index = state.list.length;
      }
      setPosition();
    });

    (async () => {
      const data = await api("/api/training/positions");
      if (!data.ok) {
        feedback.textContent = data.error || "Не удалось загрузить позиции";
        return;
      }
      state.list = data.positions || [];
      state.index = state.list.length ? 0 : -1;
      setPosition();
    })();
  }

  document.addEventListener("DOMContentLoaded", () => {
    const logoutBtn = $("#logout-btn");
    if (logoutBtn) {
      logoutBtn.addEventListener("click", async () => {
        const data = await api("/api/logout", { method: "POST" });
        if (data.ok) go(data.redirect || "/");
      });
    }
    if (page === "index") initIndex();
    if (page === "coach") initCoach();
    if (page === "menu") initMenu();
    if (page === "game") initGame();
    if (page === "tournament") initTournament();
    if (page === "profile") initProfile();
    if (page === "backups") initBackups();
    if (page === "import") initImport();
    if (page === "training") initTraining();
  });
})();
