import "../styles/tokens.css";
import { mount } from "svelte";
import App from "./App.svelte";
import { camera } from "./scene";

mount(App, { target: document.getElementById("app")! });

// For scripted checks in a headless browser.
(window as unknown as { wled: object }).wled = { camera };
