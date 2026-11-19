(function () {
  "use strict";

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.prototype.slice.call((root || document).querySelectorAll(sel));
  const PIECE_FILES = { p: "P", n: "N", b: "B", r: "R", q: "Q", k: "K" };

  function pieceImage(piece) {
    const img = document.createElement("img");
    img.className = "piece " + (piece.color === "w" ? "white" : "black");
    img.src = "/static/pieces/" + piece.color + PIECE_FILES[piece.type] + ".svg";
    img.alt = "";
    img.draggable = false;
    return img;
  }

  const LABEL_NAMES = {
    brilliant: "Блестящий",
    amethyst: "Аметистовый",
    ideal: "Идеальный",
    great: "Отличный",
    best: "Лучший",
    excellent: "Превосходный",
    good: "Хороший",
    book: "Теория",
    inaccuracy: "Неточность",
    mistake: "Ошибка",
    blunder: "Зевок",
    miss: "Упущение",
    forced: "Вынужденный"
  };

  const LABEL_MARKS = {
    brilliant: "!!",
    amethyst: "!!!",
    ideal: "∞",
    great: "!",
    best: "✓",
    excellent: "✓",
    good: "✓",
    book: "≡",
    inaccuracy: "?!",
    mistake: "?",
    blunder: "??",
    miss: "×",
    forced: "→"
  };

  const LABEL_ORDER = [
    "amethyst", "brilliant", "ideal", "great", "best", "excellent", "good",
    "book", "inaccuracy", "mistake", "blunder", "miss", "forced"
  ];

  function showToast(message) {
    const toast = $("#toast");
    if (!toast) return;
    toast.textContent = message;
    toast.classList.remove("hidden");
    clearTimeout(showToast._timer);
    showToast._timer = setTimeout(() => toast.classList.add("hidden"), 3600);
  }

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
          board["abcdefgh"[file] + (8 - rowIndex)] = { type: symbol.toLowerCase(), color };
          file += 1;
        }
      }
    });
    return board;
  }

  function squareName(fileIndex, rank) {
    return "abcdefgh"[fileIndex] + rank;
  }

  function formatEval(cp) {
    if (cp === null || cp === undefined) return "0.00";
    if (Math.abs(cp) >= 9000) return cp > 0 ? "Мат" : "Мат";
    const value = cp / 100;
    return (value > 0 ? "+" : "") + value.toFixed(2);
  }

  function iconEl(label, size) {
    const img = document.createElement("img");
    img.className = "label-icon";
    if (size) {
      img.style.width = size + "px";
      img.style.height = size + "px";
    }
    img.alt = LABEL_NAMES[label] || label;
    img.src = "/static/icons/" + label + ".svg";
    img.addEventListener("error", () => {
      const span = document.createElement("span");
      span.className = "label-mark";
      span.textContent = LABEL_MARKS[label] || "";
      img.replaceWith(span);
    });
    return img;
  }

  function initAnalysis() {
    const gameId = Number(document.body.dataset.gameId);
    const loading = $("#analysis-loading");
    const boardEl = $("#board");
    const arrowsEl = $("#board-arrows");
    const bubble = $("#label-bubble");
    const state = {
      data: null,
      index: 0,
      orientation: "white",
      fens: [],
      arrow: null,
      coach: null,
      lastSpoken: ""
    };

    async function load() {
      const response = await fetch("/api/analysis/" + gameId);
      let payload = null;
      try {
        payload = await response.json();
      } catch (error) {
        payload = { ok: false, error: "Сервер вернул некорректный ответ" };
      }
      if (!payload.ok) {
        loading.innerHTML = '<p>Не удалось разобрать партию</p><p class="hint">' +
          (payload.error || "Неизвестная ошибка") + "</p>";
        return;
      }
      state.data = payload.analysis;
      state.fens = payload.analysis.fens || [];
      state.coach = payload.analysis.coach || null;
      state.orientation = payload.analysis.user_color === "black" ? "black" : "white";
      state.index = 0;
      loading.classList.add("hidden");
      paintMeta();
      render();
    }

    function paintMeta() {
      const data = state.data;
      const resultMap = { win: "Победа", loss: "Поражение", draw: "Ничья" };
      const pill = $("#result-pill");
      const accTitles = $$(".acc-title");
      if (data.is_bot_game) {
        $("#top-name").textContent = data.white_name + " — " + data.black_name;
        $("#top-sub").textContent = "Партия ботов";
        $("#top-avatar").textContent = (data.white_name || "?").charAt(0);
        if (accTitles[0]) accTitles[0].textContent = "Белые";
        if (accTitles[1]) accTitles[1].textContent = "Чёрные";
        pill.textContent = data.result || "Партия";
      } else {
        $("#top-name").textContent = data.bot_name || "Соперник";
        $("#top-sub").textContent = (data.bot_elo || "") + " Эло";
        $("#top-avatar").textContent = (data.bot_name || "?").charAt(0);
        pill.textContent = resultMap[data.result] || "Партия";
      }
      $("#acc-user").textContent = data.accuracy.user + "%";
      $("#acc-bot").textContent = data.accuracy.bot + "%";
      const engineBadge = $("#engine-badge");
      engineBadge.textContent = data.engine === "stockfish" ? "Stockfish" : "Учебный движок";
      const coach = state.coach || {};
      const avatar = $("#trainer-avatar");
      if (avatar) {
        avatar.textContent = (coach.name || "Т").charAt(0);
        avatar.style.background = coach.color || "#3f6d8c";
      }
      $("#trainer-name").textContent = coach.name || "Тренер";
      $("#trainer-role").textContent = coach.role || "Разбор партии";
      const speakBtn = $("#speak-btn");
      const autoSpeak = $("#auto-speak");
      if (!window.ChessVoice || !window.ChessVoice.available) {
        if (speakBtn) {
          speakBtn.disabled = true;
          speakBtn.title = "Озвучка недоступна в этом браузере";
        }
        if (autoSpeak) {
          autoSpeak.checked = false;
          autoSpeak.disabled = true;
        }
      }
      renderSummary();
      renderMoveList();
    }

    function renderSummary() {
      const box = $("#label-summary");
      box.innerHTML = "";
      const counts = state.data.counts || { user: {}, bot: {} };
      LABEL_ORDER.forEach((label) => {
        const userCount = counts.user[label] || 0;
        const botCount = counts.bot[label] || 0;
        const row = document.createElement("div");
        row.className = "label-row";
        row.appendChild(iconEl(label, 18));
        const name = document.createElement("span");
        name.className = "label-name";
        name.textContent = LABEL_NAMES[label];
        row.appendChild(name);
        const value = document.createElement("span");
        value.className = "label-count";
        value.textContent = userCount + " / " + botCount;
        row.appendChild(value);
        box.appendChild(row);
      });
      if (!box.children.length) {
        const empty = document.createElement("p");
        empty.className = "hint";
        empty.textContent = "Ярлыков нет.";
        box.appendChild(empty);
      }
    }

    function renderMoveList() {
      const list = $("#move-list");
      const moves = state.data.moves || [];
      list.innerHTML = "";
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
          if (!move) {
            line.appendChild(cell);
            continue;
          }
          if (state.index === index + offset + 1) cell.classList.add("current");
          if (move.label && move.label !== "best" && move.label !== "excellent" && move.label !== "good" && move.label !== "book" && move.label !== "forced") {
            cell.appendChild(iconEl(move.label, 15));
          } else if (move.label && LABEL_MARKS[move.label]) {
            cell.appendChild(iconEl(move.label, 15));
          }
          const san = document.createElement("span");
          san.textContent = move.san;
          cell.appendChild(san);
          cell.addEventListener("click", () => {
            state.index = index + offset + 1;
            render();
            renderMoveList();
          });
          line.appendChild(cell);
        }
        list.appendChild(line);
      }
      if (!moves.length) {
        const empty = document.createElement("div");
        empty.className = "empty-moves";
        empty.textContent = "Ходов нет.";
        list.appendChild(empty);
      }
    }

    function squareCoords(square, flipped) {
      const file = square.charCodeAt(0) - 97;
      const rank = Number(square[1]);
      const x = flipped ? (7 - file) : file;
      const y = flipped ? (rank - 1) : (8 - rank);
      return { x: x, y: y };
    }

    function renderBoard() {
      const fen = state.fens[state.index] || state.fens[0];
      if (!fen) return;
      const board = parseFen(fen);
      const flipped = state.orientation === "black";
      const files = flipped ? "hgfedcba" : "abcdefgh";
      const ranks = flipped ? [1, 2, 3, 4, 5, 6, 7, 8] : [8, 7, 6, 5, 4, 3, 2, 1];
      const info = state.index > 0 ? state.data.moves[state.index - 1] : null;
      boardEl.innerHTML = "";
      ranks.forEach((rank, rankIndex) => {
        Array.from(files).forEach((file, fileIndex) => {
          const square = file + rank;
          const cell = document.createElement("div");
          const isLight = (file.charCodeAt(0) - 97 + rank) % 2 === 0;
          cell.className = "sq " + (isLight ? "light" : "dark");
          cell.dataset.square = square;
          if (info && (info.from === square || info.to === square)) cell.classList.add("last");
          const piece = board[square];
          if (piece) cell.appendChild(pieceImage(piece));
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
          boardEl.appendChild(cell);
        });
      });
    }

    function drawArrow(from, to) {
      arrowsEl.innerHTML = "";
      if (!from || !to) return;
      const flipped = state.orientation === "black";
      const a = squareCoords(from, flipped);
      const b = squareCoords(to, flipped);
      const x1 = a.x * 100 + 50;
      const y1 = a.y * 100 + 50;
      const x2 = b.x * 100 + 50;
      const y2 = b.y * 100 + 50;
      const dx = x2 - x1;
      const dy = y2 - y1;
      const length = Math.hypot(dx, dy) || 1;
      const ux = dx / length;
      const uy = dy / length;
      const startX = x1 + ux * 34;
      const startY = y1 + uy * 34;
      const endX = x2 - ux * 34;
      const endY = y2 - uy * 34;
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("x1", startX);
      line.setAttribute("y1", startY);
      line.setAttribute("x2", endX);
      line.setAttribute("y2", endY);
      line.setAttribute("stroke", "#81b64c");
      line.setAttribute("stroke-width", "15");
      line.setAttribute("stroke-linecap", "round");
      line.setAttribute("opacity", "0.92");
      arrowsEl.appendChild(line);
      const headLength = 30;
      const headWidth = 21;
      const baseX = endX - ux * headLength;
      const baseY = endY - uy * headLength;
      const px = -uy;
      const py = ux;
      const points = [
        endX + ux * 6 + "," + (endY + uy * 6),
        (baseX + px * headWidth) + "," + (baseY + py * headWidth),
        (baseX - px * headWidth) + "," + (baseY - py * headWidth)
      ].join(" ");
      const head = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
      head.setAttribute("points", points);
      head.setAttribute("fill", "#81b64c");
      head.setAttribute("opacity", "0.92");
      arrowsEl.appendChild(head);
    }

    function placeBubble(square) {
      if (!square) {
        bubble.classList.add("hidden");
        return;
      }
      const flipped = state.orientation === "black";
      const coords = squareCoords(square, flipped);
      bubble.style.left = ((coords.x + 1) * 12.5) + "%";
      bubble.style.top = (coords.y * 12.5) + "%";
      bubble.classList.remove("hidden");
    }

    function fillBubble(label) {
      const box = $("#label-bubble-icon");
      const mark = $("#label-bubble-mark");
      const img = document.createElement("img");
      img.src = "/static/icons/" + label + ".svg";
      img.alt = LABEL_NAMES[label] || label;
      img.addEventListener("error", () => {
        img.remove();
        mark.textContent = LABEL_MARKS[label] || "";
      });
      box.replaceWith(img);
      img.id = "label-bubble-icon";
      mark.textContent = "";
    }

    function speakIfAuto(text) {
      const auto = $("#auto-speak");
      if (!auto || !auto.checked) return;
      if (!text || text === state.lastSpoken) return;
      if (!window.ChessVoice || !window.ChessVoice.available) return;
      state.lastSpoken = text;
      window.ChessVoice.speak(text, state.coach);
    }

    function updateTrainer() {
      const trainer = $("#trainer-text");
      const labelEl = $("#trainer-label");
      const evalEl = $("#trainer-eval");
      const evalLine = $("#trainer-eval-line");
      const iconBox = $("#trainer-icon");
      if (state.index === 0) {
        trainer.textContent = "Стартовая позиция. Листай ходы — под доской появится разбор каждого решения.";
        labelEl.textContent = "Старт";
        evalEl.textContent = "0.00";
        if (evalLine) evalLine.textContent = "Выбери ход, чтобы услышать тренера.";
        iconBox.removeAttribute("src");
        iconBox.style.visibility = "hidden";
        state.lastSpoken = "";
        return;
      }
      const info = state.data.moves[state.index - 1];
      if (!info) return;
      const whiteBefore = info.eval_white_before !== undefined
        ? info.eval_white_before
        : (info.color === "white" ? info.before : -info.before);
      const whiteAfter = info.eval_white_after !== undefined
        ? info.eval_white_after
        : (info.color === "white" ? info.after : -info.after);
      labelEl.textContent = LABEL_NAMES[info.label] || "Ход";
      evalEl.textContent = formatEval(whiteAfter);
      trainer.textContent = info.text;
      if (evalLine) {
        evalLine.textContent = "До: " + formatEval(whiteBefore) +
          " · После: " + formatEval(whiteAfter) +
          " · Потеря: " + Number(info.loss || 0) + " cp";
      }
      iconBox.src = "/static/icons/" + info.label + ".svg";
      iconBox.alt = LABEL_NAMES[info.label] || info.label;
      iconBox.style.visibility = "visible";
      speakIfAuto(info.text);
    }

    function updateEval() {
      const fill = $("#eval-fill");
      const number = $("#eval-number");
      let percent = 50;
      let text = "0.00";
      if (state.index > 0) {
        const info = state.data.moves[state.index - 1];
        const whiteEval = info.color === "white" ? info.after : -info.after;
        percent = 50 + (whiteEval / 1600) * 100;
        if (Math.abs(whiteEval) >= 9000) percent = whiteEval > 0 ? 100 : 0;
        percent = Math.max(2, Math.min(98, percent));
        text = formatEval(whiteEval);
      }
      const narrow = window.matchMedia("(max-width: 940px)").matches;
      fill.style.height = narrow ? "100%" : percent + "%";
      fill.style.width = narrow ? percent + "%" : "100%";
      number.textContent = text;
    }

    function updateControls() {
      const total = state.data.moves.length;
      $("#move-counter").textContent = state.index + " / " + total;
      $("#nav-start").disabled = state.index === 0;
      $("#nav-prev").disabled = state.index === 0;
      $("#nav-next").disabled = state.index >= total;
      $("#nav-end").disabled = state.index >= total;
    }

    function render() {
      if (!state.data) return;
      renderBoard();
      const info = state.index > 0 ? state.data.moves[state.index - 1] : null;
      updateEval();
      updateTrainer();
      updateControls();
      if (info) {
        fillBubble(info.label);
        placeBubble(info.to);
        drawArrow(info.best_uci ? info.best_uci.slice(0, 2) : null, info.best_uci ? info.best_uci.slice(2, 4) : null);
      } else {
        bubble.classList.add("hidden");
        arrowsEl.innerHTML = "";
      }
      renderMoveList();
    }

    $("#nav-start").addEventListener("click", () => {
      state.index = 0;
      render();
    });
    $("#nav-prev").addEventListener("click", () => {
      state.index = Math.max(0, state.index - 1);
      render();
    });
    $("#nav-next").addEventListener("click", () => {
      state.index = Math.min(state.data.moves.length, state.index + 1);
      render();
    });
    $("#nav-end").addEventListener("click", () => {
      state.index = state.data.moves.length;
      render();
    });
    $("#flip-btn").addEventListener("click", () => {
      state.orientation = state.orientation === "white" ? "black" : "white";
      render();
    });

    document.addEventListener("keydown", (event) => {
      if (!state.data) return;
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        state.index = Math.max(0, state.index - 1);
        render();
      }
      if (event.key === "ArrowRight") {
        event.preventDefault();
        state.index = Math.min(state.data.moves.length, state.index + 1);
        render();
      }
    });

    const speakBtn = $("#speak-btn");
    if (speakBtn) {
      speakBtn.addEventListener("click", () => {
        const text = $("#trainer-text").textContent;
        if (window.ChessVoice && window.ChessVoice.available && text) {
          window.ChessVoice.speak(text, state.coach);
        }
      });
    }
    const autoSpeak = $("#auto-speak");
    if (autoSpeak) {
      autoSpeak.addEventListener("change", () => {
        if (!autoSpeak.checked) {
          if (window.ChessVoice) window.ChessVoice.stop();
          return;
        }
        const text = $("#trainer-text").textContent;
        if (text && state.index > 0 && window.ChessVoice) {
          state.lastSpoken = "";
          window.ChessVoice.speak(text, state.coach);
        }
      });
    }
    window.addEventListener("beforeunload", () => {
      if (window.ChessVoice) window.ChessVoice.stop();
    });

    load();
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (document.body.dataset.page === "analysis") initAnalysis();
  });
})();
