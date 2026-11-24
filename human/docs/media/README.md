# Media

Every image and video here is rendered from released files with this repository's tools.
`RELEASE` is the full ARCADE-Checkout-Human release; the episodes in the sample give identical
renders from `samples/arcade_human_sample`.

| file | command |
|---|---|
| `episode_hero.mp4`, `episode_hero.webp` | `arcade-human video RELEASE J03826_left episode_hero.mp4 --webp episode_hero.webp` |
| `episodes_grid.webp` | `arcade-human grid RELEASE J03826_left,J00272_right,J00051_right,J02562_right,J06218_left,J04596_right grid.mp4 --webp episodes_grid.webp` |
| `products.png` | `arcade-human products RELEASE products.png` |
| `episode_card.png` | `arcade-human overview samples/arcade_human_sample J03826_left episode_card.png` |

Renders need the `render` extra and ffmpeg; the card needs the `viz` extra.
