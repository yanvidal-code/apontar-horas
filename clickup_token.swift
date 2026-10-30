// clickup-token — guarda e lê o token do ClickUp no Keychain, pedindo a digital.
//
//   clickup-token gravar    # pede o token sem eco e grava; apaga o item anterior
//   clickup-token ler       # pede a digital e imprime o token no stdout
//
// Por que existe: o item criado com `security add-generic-password -T ""` abre
// o diálogo antigo do Keychain, e esse diálogo só aceita a senha do chaveiro —
// digital não entra ali. A digital vem do LocalAuthentication, que o `security`
// não chama. Então este programa pede a digital e só depois lê o item.
//
// Quem pode ler sem diálogo: só este binário. O item é criado por ele, com a
// lista de confiança contendo apenas ele mesmo; o `security` e qualquer outro
// processo caem no diálogo de senha do macOS. A confiança é pelo hash do código:
// recompilar gera outro binário, e aí é preciso rodar `gravar` de novo.
//
// Códigos de saída, os mesmos do `security` onde há equivalente:
//   0  ok            44  item não existe
//   45 item existe, mas não foi gravado por este programa (item antigo)
//   51 digital recusada ou cancelada
//   2  uso errado    1  outro erro do Keychain
//
// Compilado por `./clickup-time.sh digital`. Com `-D TESTE`, a digital é pulada e
// o serviço muda para `clickup-irrah-tech-teste`: o binário de teste tem outro
// hash, então não enxerga o item real.

import Foundation
import LocalAuthentication
import Security

#if TESTE
let servico = "clickup-irrah-tech-teste"
#else
let servico = "clickup-irrah-tech"
#endif

// Marca no atributo de comentário do item. É o que distingue o item gravado por
// este programa do criado pelo `security`: ler o antigo depois da digital ainda
// abriria o diálogo de senha, então o antigo é recusado antes de pedir a digital.
let marca = "gravado por clickup-token"

let formato = try! NSRegularExpression(pattern: "^pk_[0-9]{6,}_[0-9A-Z]{20,}$")

func sair(_ codigo: Int32, _ mensagem: String? = nil) -> Never {
    if let mensagem {
        FileHandle.standardError.write(Data((mensagem + "\n").utf8))
    }
    exit(codigo)
}

func descrever(_ status: OSStatus) -> String {
    (SecCopyErrorMessageString(status, nil) as String?) ?? "OSStatus \(status)"
}

final class Resultado: @unchecked Sendable {
    var ok = false
    var erro: Error?
}

func pedirDigital(_ motivo: String) {
    #if TESTE
    return
    #else
    let contexto = LAContext()
    var indisponivel: NSError?
    // `.deviceOwnerAuthentication`: digital, com a senha do Mac como alternativa
    // quando não há sensor (tampa fechada, teclado sem Touch ID).
    guard contexto.canEvaluatePolicy(.deviceOwnerAuthentication, error: &indisponivel) else {
        sair(51, "autenticação local indisponível: \(indisponivel?.localizedDescription ?? "?")")
    }
    let pronto = DispatchSemaphore(value: 0)
    let resultado = Resultado()
    contexto.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: motivo) { ok, erro in
        resultado.ok = ok
        resultado.erro = erro
        pronto.signal()
    }
    pronto.wait()
    if !resultado.ok {
        sair(51, "digital recusada ou cancelada: \(resultado.erro?.localizedDescription ?? "?")")
    }
    #endif
}

func atributos() -> [String: Any]? {
    // Atributo não é segredo: ler só atributos não abre diálogo nenhum.
    let consulta: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: servico,
        kSecReturnAttributes as String: true,
        kSecMatchLimit as String: kSecMatchLimitOne,
    ]
    var saida: CFTypeRef?
    let status = SecItemCopyMatching(consulta as CFDictionary, &saida)
    if status == errSecItemNotFound { return nil }
    guard status == errSecSuccess, let dicionario = saida as? [String: Any] else {
        sair(1, "não consegui consultar o Keychain: \(descrever(status))")
    }
    return dicionario
}

func ler() -> Never {
    guard let item = atributos() else {
        sair(44, "o item `\(servico)` não existe no Keychain.")
    }
    guard (item[kSecAttrComment as String] as? String) == marca else {
        sair(45, "o item `\(servico)` foi gravado pelo `security`, não por este programa.")
    }
    pedirDigital("ler o token do ClickUp para apontar horas")

    let consulta: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: servico,
        kSecReturnData as String: true,
        kSecMatchLimit as String: kSecMatchLimitOne,
    ]
    var saida: CFTypeRef?
    let status = SecItemCopyMatching(consulta as CFDictionary, &saida)
    switch status {
    case errSecSuccess:
        guard let dados = saida as? Data, let token = String(data: dados, encoding: .utf8) else {
            sair(1, "o item existe, mas o valor não é texto.")
        }
        print(token)
        exit(0)
    case errSecItemNotFound:
        sair(44, "o item `\(servico)` não existe no Keychain.")
    case errSecUserCanceled, errSecAuthFailed:
        sair(51, "acesso ao Keychain negado ou cancelado.")
    default:
        sair(1, "não consegui ler o Keychain: \(descrever(status))")
    }
}

func lerTokenDoTerminal() -> String {
    if isatty(STDIN_FILENO) == 1 {
        var buffer = [CChar](repeating: 0, count: 512)
        guard readpassphrase("Token do ClickUp (não aparece ao digitar): ", &buffer, buffer.count,
                             RPP_REQUIRE_TTY) != nil else {
            sair(2, "não consegui ler do terminal.")
        }
        let token = String(cString: buffer)
        buffer.withUnsafeMutableBufferPointer { ponteiro in
            for i in ponteiro.indices { ponteiro[i] = 0 }
        }
        return token
    }
    // Sem terminal (teste automatizado): uma linha do stdin.
    return readLine(strippingNewline: true) ?? ""
}

func gravar() -> Never {
    let token = lerTokenDoTerminal().trimmingCharacters(in: .whitespacesAndNewlines)
    let faixa = NSRange(token.startIndex..., in: token)
    guard formato.firstMatch(in: token, range: faixa) != nil else {
        sair(2, "isso não tem formato de token do ClickUp (\(token.count) caractere(s), "
             + "esperado `pk_<id>_<ALNUM>`). Nada foi gravado.")
    }

    let apagar: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: servico,
    ]
    let apagou = SecItemDelete(apagar as CFDictionary)
    guard apagou == errSecSuccess || apagou == errSecItemNotFound else {
        sair(1, "não consegui apagar o item anterior: \(descrever(apagou)).\n"
             + "Apague você mesmo e rode de novo:\n"
             + "  security delete-generic-password -s \(servico)")
    }

    // Lista de confiança explícita, só com este binário. É o padrão do SecItemAdd,
    // mas escrito aqui para ninguém precisar saber disso para confiar no resultado.
    var eu: SecTrustedApplication?
    var acesso: SecAccess?
    guard SecTrustedApplicationCreateFromPath(nil, &eu) == errSecSuccess, let eu,
          SecAccessCreate(servico as CFString, [eu] as CFArray, &acesso) == errSecSuccess,
          let acesso else {
        sair(1, "não consegui montar a lista de confiança do item.")
    }

    let item: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: servico,
        kSecAttrAccount as String: NSUserName(),
        kSecAttrLabel as String: servico,
        kSecAttrComment as String: marca,
        kSecAttrAccess as String: acesso,
        kSecValueData as String: Data(token.utf8),
    ]
    let status = SecItemAdd(item as CFDictionary, nil)
    guard status == errSecSuccess else {
        sair(1, "não consegui gravar: \(descrever(status))")
    }
    FileHandle.standardError.write(Data("gravado em `\(servico)`. A próxima leitura pede a digital.\n".utf8))
    exit(0)
}

let argumentos = CommandLine.arguments.dropFirst()
switch argumentos.first {
case "ler": ler()
case "gravar": gravar()
default: sair(2, "uso: clickup-token ler | gravar")
}
