from __future__ import annotations

import json
from pathlib import Path
import pytest

from local_ai_hub.config import load_config
from local_ai_hub.deterministic import DeterministicEngine, _is_test_file
from local_ai_hub.token_economy import DEFAULT_EXTS, _OUTLINE_PATTERN, generate_repo_map
from local_ai_hub.app import LocalAIApp


def _make_config(tmp_path: Path) -> dict:
    cfg = load_config()
    cfg["server"]["state_dir"] = str(tmp_path / "state")
    return cfg


def _write_config(tmp_path: Path) -> Path:
    cfg_file = tmp_path / "hub-config.toml"
    cfg_file.write_text(
        f'''[server]\nbind="127.0.0.1"\nport=11435\nstate_dir="{(tmp_path / 'state').as_posix()}"\nauto_start_ollama=false\n\n[hardware]\nprofile="cpu"\nauto_tune=false\n\n[prewarm]\nenabled=false\n\n[preprocessing]\nenabled=false\n\n[code_intelligence]\nenabled=false\n\n''',
        encoding="utf-8",
    )
    return cfg_file


def test_token_economy_extensions_and_outline():
    assert ".php" in DEFAULT_EXTS
    assert ".vue" in DEFAULT_EXTS
    assert ".svelte" in DEFAULT_EXTS
    assert ".mjs" in DEFAULT_EXTS
    assert ".cjs" in DEFAULT_EXTS

    # Test PHP outline regex matching
    assert _OUTLINE_PATTERN.search("final readonly class OrderAggregate {")
    assert _OUTLINE_PATTERN.search("trait LoggableTrait {")
    assert _OUTLINE_PATTERN.search("interface PaymentGatewayInterface {")
    assert _OUTLINE_PATTERN.search("enum OrderStatus: string {")
    assert _OUTLINE_PATTERN.search("public function processPayment(Order $order): bool {")

    # Test JS/TS outline regex matching
    assert _OUTLINE_PATTERN.search("export const calculateTotal = (items) => {")
    assert _OUTLINE_PATTERN.search("export interface UserProfile {")
    assert _OUTLINE_PATTERN.search("export type Result<T> = Success<T> | Failure;")


def test_php_source_facts_extraction(tmp_path: Path):
    cfg = _make_config(tmp_path)
    engine = DeterministicEngine(cfg, repo_tools=None)

    php_code = """<?php
namespace App\\Services;

use App\\Models\\User;
use Symfony\\Component\\Routing\\Annotation\\Route;

#[Route('/api/orders', methods: ['GET', 'POST'])]
#[ORM\\Entity]
final class OrderService
{
    public function __construct(private PaymentGateway $gateway) {}

    public function processOrder(User $user, float $amount): bool
    {
        add_action('order_processed', 'send_notification');
        return true;
    }
}
"""
    facts = engine._extract_source_facts("src/Services/OrderService.php", php_code)
    kinds = {f["kind"]: f for f in facts}

    assert "php_namespace" in kinds
    assert kinds["php_namespace"]["name"] == "App\\Services"

    assert "php_class" in kinds
    assert kinds["php_class"]["name"] == "OrderService"
    assert kinds["php_class"]["extra"]["fqn"] == "App\\Services\\OrderService"

    assert "php_function" in kinds
    assert any(f["name"] == "processOrder" for f in facts if f["kind"] == "php_function")

    assert "php_attribute" in kinds
    assert any(f["kind"] == "route" and f["name"] == "/api/orders" for f in facts)

    assert "wordpress_hook" in kinds
    wp_facts = [f for f in facts if f["kind"] == "wordpress_hook"]
    assert any(f["name"] == "order_processed" for f in wp_facts)


def test_js_ts_source_facts_extraction(tmp_path: Path):
    cfg = _make_config(tmp_path)
    engine = DeterministicEngine(cfg, repo_tools=None)

    ts_code = """
import React, { useState, useEffect } from 'react';

export interface UserCardProps {
    userId: string;
}

export type StatusType = 'active' | 'inactive';

@Controller('users')
export class UserController {
    @Get(':id')
    getUser() {}
}

export const UserCard: React.FC<UserCardProps> = ({ userId }) => {
    const useUserData = () => {};
    return <div>User</div>;
};

describe('UserCard component', () => {
    it('renders user details correctly', () => {});
});
"""
    facts = engine._extract_source_facts("src/components/UserCard.tsx", ts_code)
    kinds = [f["kind"] for f in facts]

    assert "react_component" in kinds
    assert "ts_interface" in kinds
    assert "ts_type" in kinds
    assert "ts_class" in kinds
    assert "test_describe" in kinds
    assert "test_it" in kinds
    assert any(f["kind"] == "route" and f["name"] == ":id" for f in facts)


def test_infra_facts_package_and_composer_json(tmp_path: Path):
    cfg = _make_config(tmp_path)
    engine = DeterministicEngine(cfg, repo_tools=None)

    pkg_json = json.dumps({
        "name": "my-cool-frontend",
        "scripts": {
            "dev": "vite",
            "build": "tsc && vite build",
            "test": "vitest"
        },
        "dependencies": {
            "react": "^18.2.0",
            "axios": "^1.6.0"
        },
        "devDependencies": {
            "typescript": "^5.2.0",
            "vitest": "^1.0.0"
        }
    })
    pkg_facts = engine._extract_infra_facts("package.json", pkg_json)
    pkg_kinds = [f["kind"] for f in pkg_facts]
    assert "package_name" in pkg_kinds
    assert "npm_script" in pkg_kinds
    assert "dependency" in pkg_kinds
    assert any(f["name"] == "build" for f in pkg_facts if f["kind"] == "npm_script")
    assert any(f["name"] == "react" for f in pkg_facts if f["kind"] == "dependency")

    composer_json = json.dumps({
        "name": "acme/payment-api",
        "require": {
            "php": "^8.2",
            "laravel/framework": "^10.0"
        },
        "require-dev": {
            "phpunit/phpunit": "^10.0"
        },
        "autoload": {
            "psr-4": {
                "App\\\\": "app/",
                "Database\\\\Factories\\\\": "database/factories/"
            }
        },
        "scripts": {
            "test": "vendor/bin/phpunit"
        }
    })
    comp_facts = engine._extract_infra_facts("composer.json", composer_json)
    comp_kinds = [f["kind"] for f in comp_facts]
    assert "package_name" in comp_kinds
    assert "psr4_autoload" in comp_kinds
    assert "composer_script" in comp_kinds
    assert any(f["name"] == "App" for f in comp_facts if f["kind"] == "psr4_autoload")
    assert any(f["name"] == "laravel/framework" for f in comp_facts if f["kind"] == "dependency")


def test_php_and_ts_test_file_recognition():
    assert _is_test_file("tests/Feature/UserTest.php")
    assert _is_test_file("tests/Unit/OrderServiceTest.php")
    assert _is_test_file("src/services/order.spec.php")
    assert _is_test_file("src/components/Button.test.tsx")
    assert _is_test_file("src/utils/math.spec.ts")
    assert _is_test_file("test/api.test.js")

    assert not _is_test_file("src/Services/OrderService.php")
    assert not _is_test_file("src/components/Button.tsx")


def test_php_and_ts_import_resolution(tmp_path: Path):
    cfg_file = _write_config(tmp_path)
    app = LocalAIApp(str(cfg_file))
    try:
        repo = tmp_path / "repo"
        (repo / "src" / "Services").mkdir(parents=True)
        (repo / "src" / "components").mkdir(parents=True)

        (repo / "src" / "Services" / "InvoiceService.php").write_text(
            "<?php\nnamespace App\\Services;\n\nclass InvoiceService {}\n",
            encoding="utf-8"
        )
        (repo / "src" / "components" / "ModalDialog.tsx").write_text(
            "export class ModalDialog {}\n",
            encoding="utf-8"
        )

        app.code_index.update_file(str(repo), "src/Services/InvoiceService.php")
        app.code_index.update_file(str(repo), "src/components/ModalDialog.tsx")

        # Resolve PHP import
        php_res = app.deterministic.resolve_imports(str(repo), ["InvoiceService"], "php")
        assert php_res["success"] is True
        assert any("use App\\Services\\InvoiceService;" in stmt for stmt in php_res["import_statements"])

        # Resolve TypeScript import
        ts_res = app.deterministic.resolve_imports(str(repo), ["ModalDialog"], "typescript")
        assert ts_res["success"] is True
        assert any("import { ModalDialog } from './src/components/ModalDialog';" in stmt for stmt in ts_res["import_statements"])
    finally:
        app.close()


def test_composer_lockfile_package_audit(tmp_path: Path):
    cfg = _make_config(tmp_path)
    engine = DeterministicEngine(cfg, repo_tools=None)

    repo_dir = tmp_path / "php_repo"
    repo_dir.mkdir(parents=True)
    composer_lock = {
        "packages": [
            {"name": "guzzlehttp/guzzle", "version": "v7.4.0"},
            {"name": "monolog/monolog", "version": "3.0.0"}
        ],
        "packages-dev": [
            {"name": "phpunit/phpunit", "version": "10.0.0"}
        ]
    }
    (repo_dir / "composer.lock").write_text(json.dumps(composer_lock), encoding="utf-8")

    res = engine.package_audit(str(repo_dir))
    assert res["success"] is True
    assert res["packages_scanned"] == 3
    assert res["vulnerabilities_found"] >= 1
    assert any(v["package"] == "guzzlehttp/guzzle" for v in res["vulnerabilities"])


def test_extract_api_spec_php_and_nextjs(tmp_path: Path):
    cfg = _make_config(tmp_path)
    engine = DeterministicEngine(cfg, repo_tools=None)

    repo_dir = tmp_path / "web_repo"
    (repo_dir / "routes").mkdir(parents=True)
    (repo_dir / "app" / "api" / "users").mkdir(parents=True)

    (repo_dir / "routes" / "api.php").write_text(
        "<?php\nRoute::get('/users', [UserController::class, 'index']);\nRoute::post('/users', [UserController::class, 'store']);\n",
        encoding="utf-8"
    )

    (repo_dir / "app" / "api" / "users" / "route.ts").write_text(
        "export async function GET(request: Request) {}\nexport async function POST(request: Request) {}\n",
        encoding="utf-8"
    )

    res = engine.extract_api_spec(str(repo_dir))
    assert res["success"] is True
    assert res["total_endpoints"] >= 3
    endpoints = res["endpoints"]
    assert any(ep["method"] == "GET" and ep["path"] == "/users" for ep in endpoints)
    assert any(ep["method"] == "POST" and ep["path"] == "/users" for ep in endpoints)


def test_html_and_blade_extraction(tmp_path: Path):
    cfg = _make_config(tmp_path)
    engine = DeterministicEngine(cfg, repo_tools=None)

    html_code = """
<!DOCTYPE html>
<html>
<head>
    <link rel="stylesheet" href="/assets/main.css">
    <script src="/assets/bundle.js"></script>
</head>
<body>
    <form action="/login" method="POST">
        <input id="user-email" type="email" name="email">
        <button type="submit">Login</button>
    </form>
    <my-custom-widget id="widget-1"></my-custom-widget>
</body>
</html>
"""
    facts = engine._extract_source_facts("index.html", html_code)
    kinds = [f["kind"] for f in facts]
    assert "html_form" in kinds
    assert "html_stylesheet" in kinds
    assert "html_script" in kinds
    assert "html_id" in kinds
    assert "web_component" in kinds
    assert any(f["kind"] == "route" and f["name"] == "/login" for f in facts)

    blade_code = """
@extends('layouts.app')
@section('content')
    <h1>Dashboard</h1>
    @include('partials.stats')
    @livewire('user-table')
@endsection
"""
    b_facts = engine._extract_source_facts("resources/views/dashboard.blade.php", blade_code)
    b_kinds = [f["kind"] for f in b_facts]
    assert "blade_extends" in b_kinds
    assert "blade_section" in b_kinds
    assert "blade_include" in b_kinds
    assert "blade_livewire" in b_kinds


def test_css_facts_extraction(tmp_path: Path):
    cfg = _make_config(tmp_path)
    engine = DeterministicEngine(cfg, repo_tools=None)

    css_code = """
:root {
    --primary-color: #3b82f6;
    --font-stack: 'Inter', sans-serif;
}

@keyframes fadeIn {
    from { opacity: 0; }
    to { opacity: 1; }
}

@media (max-width: 768px) {
    .responsive-card { display: block; }
}

.main-header {
    background: var(--primary-color);
}
"""
    facts = engine._extract_source_facts("styles/theme.css", css_code)
    kinds = [f["kind"] for f in facts]
    assert "css_variable" in kinds
    assert any(f["name"] == "--primary-color" for f in facts if f["kind"] == "css_variable")
    assert "css_keyframes" in kinds
    assert any(f["name"] == "fadeIn" for f in facts if f["kind"] == "css_keyframes")
    assert "css_media_query" in kinds
    assert "css_class" in kinds


def test_deep_laravel_extraction(tmp_path: Path):
    cfg = _make_config(tmp_path)
    engine = DeterministicEngine(cfg, repo_tools=None)

    model_code = """<?php
namespace App\\Models;

use Illuminate\\Database\\Eloquent\\Model;
use Illuminate\\Database\\Eloquent\\Relations\\HasMany;

class Post extends Model
{
    protected $table = 'blog_posts';
    protected $fillable = ['title', 'slug', 'content'];

    public function comments(): HasMany
    {
        return $this->hasMany(Comment::class);
    }
}
"""
    m_facts = engine._extract_source_facts("app/Models/Post.php", model_code)
    m_kinds = [f["kind"] for f in m_facts]
    assert "eloquent_table" in m_kinds
    assert "eloquent_fillable" in m_kinds
    assert "eloquent_relation" in m_kinds
    assert any(f["name"] == "blog_posts" for f in m_facts if f["kind"] == "eloquent_table")

    migration_code = """<?php
use Illuminate\\Database\\Migrations\\Migration;
use Illuminate\\Database\\Schema\\Blueprint;
use Illuminate\\Support\\Facades\\Schema;

return new class extends Migration {
    public function up(): void {
        Schema::create('blog_posts', function (Blueprint $table) {
            $table->id();
            $table->string('title');
            $table->text('content');
            $table->timestamps();
        });
    }
};
"""
    mig_facts = engine._extract_source_facts("database/migrations/2026_01_01_create_posts.php", migration_code)
    mig_kinds = [f["kind"] for f in mig_facts]
    assert "db_table" in mig_kinds
    assert "db_column" in mig_kinds
    assert any(f["name"] == "blog_posts" for f in mig_facts if f["kind"] == "db_table")

    artisan_code = """<?php
namespace App\\Console\\Commands;
use Illuminate\\Console\\Command;

class SendEmails extends Command {
    protected $signature = 'mail:send {user}';
}
"""
    art_facts = engine._extract_source_facts("app/Console/Commands/SendEmails.php", artisan_code)
    assert any(f["kind"] == "artisan_command" and f["name"] == "mail:send" for f in art_facts)


def test_cakephp_extraction_and_routes(tmp_path: Path):
    cfg = _make_config(tmp_path)
    engine = DeterministicEngine(cfg, repo_tools=None)

    routes_code = """<?php
use Cake\\Routing\\RouteBuilder;

return static function (RouteBuilder $routes): void {
    $routes->connect('/articles', ['controller' => 'Articles', 'action' => 'index']);
    $routes->resources('Comments');
};
"""
    r_facts = engine._extract_source_facts("config/routes.php", routes_code)
    assert any(f["kind"] == "route" and f["name"] == "/articles" for f in r_facts)
    assert any(f["kind"] == "route" and f["name"] == "/Comments" for f in r_facts)

    table_code = """<?php
namespace App\\Model\\Table;
use Cake\\ORM\\Table;

class ArticlesTable extends Table
{
    public function initialize(array $config): void
    {
        $this->hasMany('Comments');
        $this->belongsTo('Users');
    }
}
"""
    tbl_facts = engine._extract_source_facts("src/Model/Table/ArticlesTable.php", table_code)
    assert any(f["kind"] == "cake_table" and f["name"] == "ArticlesTable" for f in tbl_facts)
    assert any(f["kind"] == "cake_association" and f["name"] == "Comments" for f in tbl_facts)
