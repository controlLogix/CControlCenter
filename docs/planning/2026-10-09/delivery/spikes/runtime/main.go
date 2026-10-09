// A bounded NATS wire-format check, not the proposed Agentmux kernel.
package main

import (
    "encoding/json"
    "fmt"
    "os"
    "reflect"
    "time"

    "github.com/nats-io/nats.go"
)

func main() {
    if err := run(); err != nil {
        fmt.Fprintln(os.Stderr, err)
        os.Exit(1)
    }
}

func run() error {
    nc, err := nats.Connect(os.Getenv("AMX_SPIKE_URL"),
        nats.Token(os.Getenv("AMX_SPIKE_TOKEN")), nats.Timeout(2*time.Second), nats.NoReconnect())
    if err != nil { return err }
    defer nc.Close()
    payload := []byte(os.Getenv("AMX_SPIKE_PAYLOAD"))
    msg, err := nc.Request(os.Getenv("AMX_SPIKE_SUBJECT"), payload, 2*time.Second)
    if err != nil { return err }
    var want any
    var got struct { Request any `json:"request"`; Server string `json:"server"` }
    if err := json.Unmarshal(payload, &want); err != nil { return err }
    if err := json.Unmarshal(msg.Data, &got); err != nil { return err }
    if got.Server != "python" || !reflect.DeepEqual(got.Request, want) {
        return fmt.Errorf("NATS response changed the request")
    }
    fmt.Println(`{"client":"go","ok":true}`)
    return nil
}
