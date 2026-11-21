import "./styles.css";
import { mount } from "svelte";
import App from "./App.svelte";
import { app } from "./lib/state.svelte";

mount(App, { target: document.getElementById("app")! });

// For scripted checks in a headless browser.
(window as unknown as { treemap: object }).treemap = { app };
