import './style.css';
import './workbench.css';
import { mount } from 'svelte';
import App from './App.svelte';
import {initializeBranding} from './sportsBranding';

void initializeBranding().finally(() => mount(App, { target: document.getElementById('app')! }));
