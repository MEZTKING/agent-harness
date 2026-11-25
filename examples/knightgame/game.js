(function () {
  'use strict';

  // Canvas setup
  const canvas = document.getElementById('gameCanvas');
  const ctx = canvas.getContext('2d');
  ctx.imageSmoothingEnabled = false;

  // World metrics
  const CANVAS_WIDTH = 960;
  const CANVAS_HEIGHT = 480;
  const TILE_SIZE = 32;
  const GROUND_TOP = 416;

  const KNIGHT_WIDTH = 64;
  const KNIGHT_HEIGHT = 64;
  const COIN_SIZE = 32;

  const MOVE_SPEED = 220; // px/s
  const JUMP_VELOCITY = -520; // px/s
  const GRAVITY = 1400; // px/s^2

  // Asset sources. These are the only images used by the game.
  const assetSources = {
    knight: 'assets/knight.png',
    coin: 'assets/coin.png',
    tile: 'assets/tile.png'
  };

  function loadImage(src) {
    return new Promise(function (resolve, reject) {
      const img = new Image();
      img.onload = function () {
        resolve(img);
      };
      img.onerror = function () {
        reject(new Error('Failed to load image: ' + src));
      };
      img.src = src;
    });
  }

  const knight = {
    x: 120,
    y: GROUND_TOP - KNIGHT_HEIGHT,
    width: KNIGHT_WIDTH,
    height: KNIGHT_HEIGHT,
    vy: 0,
    facingLeft: false,
    onGround: true
  };

  const keys = {
    left: false,
    right: false
  };
  let jumpQueued = false;
  let score = 0;
  let elapsedTime = 0;
  let coins = [];
  let knightImage;
  let coinImage;
  let tileImage;

  function createCoins() {
    // Varied horizontal positions and collectible heights above the ground.
    const positions = [
      { x: 260, y: 336 },
      { x: 420, y: 288 },
      { x: 560, y: 240 },
      { x: 700, y: 272 },
      { x: 820, y: 320 }
    ];

    coins = positions.map(function (pos) {
      return {
        x: pos.x,
        y: pos.y,
        width: COIN_SIZE,
        height: COIN_SIZE
      };
    });
  }

  function rectsOverlap(a, b) {
    return a.x < b.x + b.width &&
      a.x + a.width > b.x &&
      a.y < b.y + b.height &&
      a.y + a.height > b.y;
  }

  function handleKeyDown(event) {
    if (event.key === 'ArrowLeft') {
      keys.left = true;
      event.preventDefault();
    } else if (event.key === 'ArrowRight') {
      keys.right = true;
      event.preventDefault();
    } else if (event.key === ' ' || event.code === 'Space') {
      if (!event.repeat) {
        jumpQueued = true;
      }
      event.preventDefault();
    }
  }

  function handleKeyUp(event) {
    if (event.key === 'ArrowLeft') {
      keys.left = false;
      event.preventDefault();
    } else if (event.key === 'ArrowRight') {
      keys.right = false;
      event.preventDefault();
    } else if (event.key === ' ' || event.code === 'Space') {
      event.preventDefault();
    }
  }

  function update(dt) {
    elapsedTime += dt;

    let vx = 0;
    if (keys.left) {
      vx -= MOVE_SPEED;
      knight.facingLeft = true;
    }
    if (keys.right) {
      vx += MOVE_SPEED;
      knight.facingLeft = false;
    }

    knight.x += vx * dt;

    // Keep the knight inside the canvas horizontally.
    if (knight.x < 0) {
      knight.x = 0;
    } else if (knight.x + knight.width > CANVAS_WIDTH) {
      knight.x = CANVAS_WIDTH - knight.width;
    }

    // Jump only from the ground.
    if (jumpQueued && knight.onGround) {
      knight.vy = JUMP_VELOCITY;
      knight.onGround = false;
    }
    jumpQueued = false;

    // Gravity and vertical integration.
    knight.vy += GRAVITY * dt;
    knight.y += knight.vy * dt;

    // Land on top of the ground.
    if (knight.y + knight.height >= GROUND_TOP) {
      knight.y = GROUND_TOP - knight.height;
      knight.vy = 0;
      knight.onGround = true;
    }

    // Collect overlapping coins.
    coins = coins.filter(function (coin) {
      if (rectsOverlap(knight, coin)) {
        score += 1;
        return false;
      }
      return true;
    });
  }

  function drawGround() {
    for (let y = GROUND_TOP; y < CANVAS_HEIGHT; y += TILE_SIZE) {
      for (let x = 0; x < CANVAS_WIDTH; x += TILE_SIZE) {
        ctx.drawImage(tileImage, x, y, TILE_SIZE, TILE_SIZE);
      }
    }
  }

  function drawKnight() {
    ctx.save();
    if (knight.facingLeft) {
      ctx.translate(knight.x + knight.width, 0);
      ctx.scale(-1, 1);
      ctx.drawImage(knightImage, 0, knight.y, knight.width, knight.height);
    } else {
      ctx.drawImage(knightImage, knight.x, knight.y, knight.width, knight.height);
    }
    ctx.restore();
  }

  function drawCoins() {
    const spinScale = Math.abs(Math.cos(elapsedTime * 4));

    coins.forEach(function (coin) {
      const centerX = coin.x + coin.width / 2;
      const centerY = coin.y + coin.height / 2;

      ctx.save();
      ctx.translate(centerX, centerY);
      ctx.scale(spinScale, 1);
      ctx.drawImage(coinImage, -coin.width / 2, -coin.height / 2, coin.width, coin.height);
      ctx.restore();
    });
  }

  function drawScore() {
    ctx.font = 'bold 28px monospace';
    ctx.fillStyle = '#1f2937';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillText('Score: ' + score, 16, 16);
  }

  function drawWinMessage() {
    if (coins.length > 0) {
      return;
    }

    ctx.font = 'bold 36px monospace';
    ctx.fillStyle = '#14532d';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('All coins collected!', CANVAS_WIDTH / 2, 64);
  }

  function draw() {
    // Sky background (keeps the HUD readable above the grass).
    ctx.fillStyle = '#a8d8f0';
    ctx.fillRect(0, 0, CANVAS_WIDTH, GROUND_TOP);

    drawGround();
    drawCoins();
    drawKnight();
    drawScore();
    drawWinMessage();
  }

  let lastTime = 0;

  function gameLoop(timestamp) {
    const dt = Math.min((timestamp - lastTime) / 1000, 0.05);
    lastTime = timestamp;

    update(dt);
    draw();

    window.requestAnimationFrame(gameLoop);
  }

  function startGame(images) {
    knightImage = images[0];
    coinImage = images[1];
    tileImage = images[2];

    createCoins();

    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('keyup', handleKeyUp);

    lastTime = performance.now();
    window.requestAnimationFrame(gameLoop);
  }

  Promise.all([
    loadImage(assetSources.knight),
    loadImage(assetSources.coin),
    loadImage(assetSources.tile)
  ]).then(startGame).catch(function (error) {
    console.error('Game failed to start because an asset could not be loaded:', error.message);
  });
})();
