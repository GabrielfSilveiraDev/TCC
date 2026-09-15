-- schema.sql — TCC Remunerações TCE | SQL Server 2019+
-- Recria o banco do zero com estrutura limpa e bem documentada.
-- ATENÇÃO: faz DROP DATABASE remuneracao_tce se ele existir (apaga os dados carregados).
-- Em ambiente novo, prefira `docker compose up -d`, que só aplica este script se o banco não existir.
-- Execução manual: sqlcmd -S localhost,1433 -U sa -P "<DB_PASSWORD do .env>" -C -i schema.sql

USE master;
GO

SET QUOTED_IDENTIFIER ON;
GO

SET ANSI_NULLS ON;
GO

-- ============================================================================
-- 0. Drop do banco anterior (se existir)
-- ============================================================================
IF EXISTS (SELECT name FROM sys.databases WHERE name = 'remuneracao_tce')
BEGIN
    ALTER DATABASE remuneracao_tce SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
    DROP DATABASE remuneracao_tce;
END
GO

CREATE DATABASE remuneracao_tce
    COLLATE Latin1_General_100_CI_AS_SC_UTF8;
GO

USE remuneracao_tce;
GO

-- ============================================================================
-- 1. Dimensão: Estado
-- ============================================================================
CREATE TABLE dbo.dim_estado (
    estado_id   TINYINT      NOT NULL,
    sigla       CHAR(2)      NOT NULL,
    nome        VARCHAR(50)  NOT NULL,
    CONSTRAINT PK_dim_estado       PRIMARY KEY CLUSTERED (estado_id),
    CONSTRAINT UQ_dim_estado_sigla UNIQUE (sigla)
);
GO

INSERT INTO dbo.dim_estado (estado_id, sigla, nome) VALUES
    (1, 'ES', 'Espírito Santo'),
    (2, 'SP', 'São Paulo'),
    (3, 'MG', 'Minas Gerais'),
    (4, 'RS', 'Rio Grande do Sul'),
    (5, 'PR', 'Paraná'),
    (6, 'SC', 'Santa Catarina'),
    (7, 'RJ', 'Rio de Janeiro');
GO

-- ============================================================================
-- 2. Dimensão: Cargo
-- ============================================================================
CREATE TABLE dbo.dim_cargo (
    cargo_id    INT           NOT NULL IDENTITY(1,1),
    descricao   NVARCHAR(300) NOT NULL,
    CONSTRAINT PK_dim_cargo       PRIMARY KEY CLUSTERED (cargo_id),
    CONSTRAINT UQ_dim_cargo_descr UNIQUE (descricao)
);
GO

-- ============================================================================
-- 3. Fato: Remuneração mensal
--
-- Modelo conceitual das 3 colunas base:
--   salario_base  = remuneração fixa e permanente do cargo
--                   (vencimento, subsídio, cargo efetivo, vantagens fixas)
--   beneficios    = verbas adicionais variáveis ou eventuais
--                   (gratificações, auxílios alimentação/saúde/transporte,
--                    férias/1/3 férias, 13° salário, abono permanência,
--                    funções gratificadas, indenizações, parcelas indenizatórias)
--   descontos     = deduções — sempre armazenadas como valor POSITIVO
--                   (INSS/Previdência, Imposto de Renda, redutor constitucional,
--                    faltas, outros descontos obrigatórios/voluntários)
--
-- Colunas calculadas (PERSISTED para performance):
--   rendimento_bruto = salario_base + beneficios          (total bruto do mês)
--   salario_liquido  = rendimento_bruto - descontos       (valor efetivamente recebido)
-- ============================================================================
CREATE TABLE dbo.fato_remuneracao (
    -- Identificadores
    id              BIGINT          NOT NULL IDENTITY(1,1),
    estado_id       TINYINT         NOT NULL,
    cargo_id        INT             NULL,
    matricula       VARCHAR(30)     NULL,
    nome            NVARCHAR(200)   NULL,
    lotacao         NVARCHAR(200)   NULL,
    situacao        VARCHAR(50)     NULL,

    -- Período de referência
    mes             TINYINT         NOT NULL,
    ano             SMALLINT        NOT NULL,

    -- Valores monetários (R$, 2 casas decimais)
    salario_base    DECIMAL(14,2)   NOT NULL CONSTRAINT DF_fato_salario_base DEFAULT 0,
    beneficios      DECIMAL(14,2)   NOT NULL CONSTRAINT DF_fato_beneficios   DEFAULT 0,
    descontos       DECIMAL(14,2)   NOT NULL CONSTRAINT DF_fato_descontos    DEFAULT 0,

    -- Colunas calculadas persistidas
    rendimento_bruto AS CAST(salario_base + beneficios             AS DECIMAL(14,2)) PERSISTED,
    salario_liquido  AS CAST(salario_base + beneficios - descontos AS DECIMAL(14,2)) PERSISTED,

    -- Auditoria
    data_carga      DATETIME2(0)    NOT NULL CONSTRAINT DF_fato_data_carga   DEFAULT SYSDATETIME(),

    -- Constraints de integridade
    CONSTRAINT PK_fato_remuneracao PRIMARY KEY CLUSTERED (id),
    CONSTRAINT FK_fato_estado      FOREIGN KEY (estado_id) REFERENCES dbo.dim_estado (estado_id),
    CONSTRAINT FK_fato_cargo       FOREIGN KEY (cargo_id)  REFERENCES dbo.dim_cargo  (cargo_id),
    CONSTRAINT CHK_fato_mes        CHECK (mes  BETWEEN 1 AND 12),
    CONSTRAINT CHK_fato_ano        CHECK (ano  BETWEEN 2000 AND 2100),
    CONSTRAINT CHK_fato_descontos  CHECK (descontos >= 0)
);
GO

-- ============================================================================
-- 4. Índices para queries do dashboard
-- ============================================================================

-- Unicidade natural: uma linha por servidor (matrícula) por estado + período
CREATE UNIQUE NONCLUSTERED INDEX UQ_fato_natural
    ON dbo.fato_remuneracao (estado_id, matricula, mes, ano)
    WHERE matricula IS NOT NULL;
GO

-- Listagem principal e overview histórico (filtro estado + período)
CREATE NONCLUSTERED INDEX IX_fato_estado_periodo
    ON dbo.fato_remuneracao (estado_id, ano, mes)
    INCLUDE (cargo_id, nome, matricula, rendimento_bruto, salario_liquido);
GO

-- Análise por cargo
CREATE NONCLUSTERED INDEX IX_fato_cargo_periodo
    ON dbo.fato_remuneracao (cargo_id, ano, mes)
    INCLUDE (estado_id, salario_base, beneficios, descontos);
GO

-- Histórico individual por matrícula
CREATE NONCLUSTERED INDEX IX_fato_matricula
    ON dbo.fato_remuneracao (estado_id, matricula)
    WHERE matricula IS NOT NULL;
GO

-- Busca e filtro por nome
CREATE NONCLUSTERED INDEX IX_fato_nome
    ON dbo.fato_remuneracao (nome, estado_id)
    INCLUDE (ano, mes, rendimento_bruto, salario_liquido);
GO

-- Ranking e ordenação por rendimento bruto
CREATE NONCLUSTERED INDEX IX_fato_rendimento
    ON dbo.fato_remuneracao (rendimento_bruto DESC)
    INCLUDE (estado_id, cargo_id, nome, matricula, ano, mes);
GO

-- ============================================================================
-- 5. View principal — usada por todos os endpoints da API
-- ============================================================================
CREATE OR ALTER VIEW dbo.vw_remuneracao_completa AS
SELECT
    f.id,
    e.sigla                                                                       AS estado,
    f.matricula,
    f.nome,
    c.descricao                                                                   AS cargo,
    f.lotacao,
    f.situacao,
    f.mes,
    f.ano,
    RIGHT('0' + CAST(f.mes AS VARCHAR(2)), 2) + '/' + CAST(f.ano AS VARCHAR(4)) AS mes_ano,
    f.salario_base,
    f.beneficios,
    f.descontos,
    f.rendimento_bruto,
    f.salario_liquido,
    f.data_carga
FROM      dbo.fato_remuneracao f
JOIN      dbo.dim_estado       e ON e.estado_id = f.estado_id
LEFT JOIN dbo.dim_cargo        c ON c.cargo_id  = f.cargo_id;
GO


