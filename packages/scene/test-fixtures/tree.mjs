/* A recorded-looking device tree, shaped exactly as /api/devices/tree returns
 * one: dashboard/devicetree.py's tree(merge(...)).
 *
 * Deliberately NOT under test/ — node --test treats every .mjs inside a
 * directory named `test` as a suite, and a fixture file that reports zero
 * tests in the summary is a permanent small lie in the run output.
 *
 * It covers every case the renderer has a rule for:
 *
 *   10.10.4.11  a port answered and the OUI named a vendor. An inference.
 *   10.10.4.12  swept AND answered ListIdentity, agreeing. A statement, and
 *               the case that proves a corroborating sweep must not downgrade
 *               a device that spoke for itself.
 *   10.10.4.20  the OUI table and the device disagree about the vendor, with
 *               an OPC UA endpoint list that is party to neither claim.
 *   10.10.4.31  an operator already saved it. A human assertion.
 *   10.10.9.5   OPC UA only.
 *   10.10.9.7   a bare open port with no vendor at all.
 */

export const TREE = {
  groups: [
    {
      network: '10.10.4.0/24',
      count: 4,
      self_reported: 2,
      devices: [
        {
          address: '10.10.4.11',
          sources: ['segment-scan'],
          hostname: null,
          mac: '00:1d:9c:11:22:33',
          vendor: 'Rockwell Automation',
          vendor_source: 'segment-scan (OUI)',
          ports: [{ port: 44818, service: 'ethernet-ip' }],
          identity: null,
          endpoints: [],
          promoted: null,
          conflicts: [],
          suggested: ['ethernet-ip'],
        },
        {
          address: '10.10.4.12',
          sources: ['segment-scan', 'cip-listidentity'],
          hostname: 'cell4-plc',
          mac: '00:1d:9c:44:55:66',
          vendor: 'Rockwell Automation',
          vendor_source: 'cip-listidentity (the device said so)',
          ports: [{ port: 44818, service: 'ethernet-ip' }],
          identity: {
            product_name: '1756-L83E/B',
            product_code: 213,
            vendor: 'Rockwell Automation',
            device_type: 'Programmable Logic Controller',
            revision: '32.11',
            serial: '0x60A41C9D',
            state: 3,
            status: 96,
          },
          endpoints: [],
          promoted: null,
          conflicts: [],
          suggested: ['ethernet-ip'],
        },
        {
          address: '10.10.4.20',
          sources: ['segment-scan', 'cip-listidentity', 'opcua-endpoints'],
          hostname: null,
          mac: '00:0e:8c:aa:bb:cc',
          vendor: 'Rockwell Automation',
          vendor_source: 'cip-listidentity (the device said so)',
          ports: [
            { port: 44818, service: 'ethernet-ip' },
            { port: 4840, service: 'opc-ua' },
          ],
          identity: {
            product_name: 'PowerFlex 755',
            product_code: 121,
            vendor: 'Rockwell Automation',
            device_type: 'AC Drive',
            revision: '13.2',
            serial: '0x40B27711',
            state: 3,
            status: 96,
          },
          endpoints: ['opc.tcp://10.10.4.20:4840'],
          promoted: null,
          conflicts: [
            {
              field: 'vendor',
              values: [
                { value: 'Siemens AG', source: 'segment-scan (OUI)' },
                { value: 'Rockwell Automation', source: 'cip-listidentity' },
              ],
            },
          ],
          suggested: ['ethernet-ip', 'opc-ua'],
        },
        {
          address: '10.10.4.31',
          sources: ['segment-scan', 'promoted'],
          hostname: 'cell4-hmi',
          mac: '00:11:22:33:44:55',
          vendor: 'Pro-face',
          vendor_source: 'segment-scan (OUI)',
          ports: [{ port: 502, service: 'modbus-tcp' }],
          identity: null,
          endpoints: [],
          promoted: { id: 7, name: 'Cell 4 HMI', kind: 'segment-scan', port: 502, protocol: 'modbus-tcp' },
          conflicts: [],
          suggested: ['modbus-tcp'],
        },
      ],
    },
    {
      network: '10.10.9.0/24',
      count: 2,
      self_reported: 1,
      devices: [
        {
          address: '10.10.9.5',
          sources: ['opcua-endpoints'],
          hostname: null,
          mac: null,
          vendor: null,
          vendor_source: null,
          ports: [],
          identity: null,
          endpoints: ['opc.tcp://10.10.9.5:4840'],
          promoted: null,
          conflicts: [],
          suggested: ['opc-ua'],
        },
        {
          address: '10.10.9.7',
          sources: ['segment-scan'],
          hostname: null,
          mac: null,
          vendor: null,
          vendor_source: null,
          ports: [{ port: 102, service: 's7comm' }],
          identity: null,
          endpoints: [],
          promoted: null,
          conflicts: [],
          suggested: ['s7comm'],
        },
      ],
    },
  ],
  total: 6,
  conflicts: 1,
  scan: { cidr: '10.10.0.0/16', at: '2026-09-25T10:14:02Z' },
  sources: ['promoted', 'cip-listidentity', 'opcua-endpoints', 'segment-scan'],
};

/** A deep copy, so a test that mutates cannot poison the one after it. */
export function tree() {
  return structuredClone(TREE);
}

export function allRows() {
  return tree().groups.flatMap((g) => g.devices);
}

/** Deterministic shuffle, so an order-independence test is reproducible. */
export function shuffle(list, seed = 7) {
  const out = [...list];
  let s = seed;
  for (let i = out.length - 1; i > 0; i -= 1) {
    s = (s * 1103515245 + 12345) & 0x7fffffff;
    const j = s % (i + 1);
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}
