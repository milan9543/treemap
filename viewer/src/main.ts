import "./styles/tokens.css";
import "./styles/base.css";
import { mount } from "svelte";
import * as controls from "./3d/controls";
import * as scene from "./3d/scene";
import App from "./App.svelte";
import { start } from "./lib/actions";
import { app } from "./lib/state.svelte";

mount(App, { target: document.getElementById("app")! });

// For scripted checks in a headless browser.
(window as unknown as { treemap: object }).treemap = { camera: scene.camera, controls, state: app };

start();
